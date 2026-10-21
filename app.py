import os
import re
import json
import time
import sys
import threading
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, render_template
import requests
from requests.adapters import HTTPAdapter

from concurrent.futures import ThreadPoolExecutor, as_completed

# Raise Pillow's decompression-bomb limit so large botanical TIFFs are handled
# without warnings. These are known, trusted local files.
import PIL.Image
PIL.Image.MAX_IMAGE_PIXELS = None

# Create a shared requests Session with connection pooling for Keep-Alive support
http_session = requests.Session()
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)


import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)

# Constants
DEFAULT_USER_AGENT = "BotanicalScraper/1.0 (hobbyist/personal use)"
DATA_DIR = Path("data")
COLLECTION_DIR = Path("Coleccion_Botanica")

# Global lock for rate limiting requests across all threads and background processes
rate_limit_lock = threading.Lock()
last_request_time = 0.0

# Active background tasks and logging systems
active_tasks = {} # maps family -> {"thread": Thread, "cancel_event": Event, "status": str, "total": int, "completed": int, "errors": int}
active_scans = {} # maps family -> {"status": str, "tree": dict, "files_count": int, "error": str}
recent_logs = []
log_counter = 0
logs_lock = threading.Lock()

from pywikibot_scraper import PywikibotCategoryCrawler
pywikibot_crawler = PywikibotCategoryCrawler()

global_status_path = COLLECTION_DIR / "global_status.json"
global_status_lock = threading.Lock()
_global_status_cache = {"data": None, "ts": 0}  # TTL cache for /api/global-status

def load_global_status():
    with global_status_lock:
        if not global_status_path.exists():
            return {}
        try:
            with open(global_status_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
            
def save_global_status(data):
    global _global_status_cache
    with global_status_lock:
        try:
            with open(global_status_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            _global_status_cache["ts"] = 0  # invalidate cache
        except Exception as e:
            print(f"Error al guardar global_status: {e}")

def get_consolidated_status():
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    if not index_json_path.exists():
        return {}
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    global_status = load_global_status()
    updated = False
    
    for name, path_str in families_map.items():
        family_dir = Path(path_str)
        local_files = 0
        if family_dir.exists():
            IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.tif', '.tiff', '.pdf', '.webp', '.bmp'}
            local_files = sum(
                1 for x in family_dir.rglob("*")
                if x.is_file()
                and x.suffix.lower() in IMAGE_EXTS
                and ".thumbnails" not in x.parts
            )


        files_list_path = family_dir / "files_list.json"
        scanned = files_list_path.exists()
        
        commons_files = 0
        if scanned:
            cached = global_status.get(name, {})
            cached_count = cached.get("commons_files", 0) if cached.get("scanned") else 0
            if cached_count > 0:
                # Trust cached value — avoids re-reading large JSON files every call
                commons_files = cached_count
            else:
                # Cache missing or stale (0 despite being scanned) — re-read from disk
                try:
                    with open(files_list_path, "r", encoding="utf-8") as f_list:
                        commons_files = len(json.load(f_list))
                except:
                    pass
        else:
            commons_files = 0

            
        progress = 0.0
        if commons_files > 0:
            progress = round((local_files / commons_files) * 100, 1)
            if progress > 100.0:
                progress = 100.0
                
        if name not in global_status:
            global_status[name] = {
                "scanned": scanned,
                "commons_files": commons_files,
                "local_files": local_files,
                "progress": progress,
                "last_scan": time.strftime("%Y-%m-%d %H:%M") if scanned else None
            }
            updated = True
        else:
            info = global_status[name]
            if info["scanned"] != scanned or info["local_files"] != local_files or info["commons_files"] != commons_files:
                info["scanned"] = scanned
                info["commons_files"] = commons_files
                info["local_files"] = local_files
                info["progress"] = progress
                if scanned and not info.get("last_scan"):
                    info["last_scan"] = time.strftime("%Y-%m-%d %H:%M")
                updated = True
                
    if updated:
        save_global_status(global_status)
        
    return global_status

APP_LOG_PATH = COLLECTION_DIR / "app.log"
BATCH_LOG_PATH = COLLECTION_DIR / "batch_scan.log"

def add_log(message):
    """Appends a log message thread-safely with an incremental ID and persists it to app.log without blocking HTTP threads."""
    global log_counter
    formatted = f"[{time.strftime('%H:%M:%S')}] {message}"
    with logs_lock:
        log_counter += 1
        recent_logs.append({"id": log_counter, "text": formatted})
        if len(recent_logs) > 500:
            recent_logs.pop(0)

    try:
        with open(APP_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

    try:
        print(formatted)
    except Exception:
        pass

def rate_limited_request(url, headers, params=None, stream=False, timeout=20):
    """Polite non-blocking rate-limiting: releases lock before sleeping to avoid freezing HTTP server threads."""
    global last_request_time
    
    if "api.php" in url:
        min_interval = 0.5
    elif "upload.wikimedia.org" in url:
        min_interval = 0.1
    else:
        min_interval = 0.5
        
    max_attempts = 5
    for attempt in range(max_attempts):
        with rate_limit_lock:
            now = time.time()
            target_time = max(now, last_request_time + min_interval)
            last_request_time = target_time
            sleep_dur = target_time - now
            
        if sleep_dur > 0:
            time.sleep(sleep_dur)
            
        try:
            if stream:
                resp = http_session.get(url, headers=headers, params=params, stream=True, timeout=timeout)
            else:
                resp = http_session.get(url, headers=headers, params=params, timeout=timeout)
                
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_seconds = int(retry_after) if (retry_after and retry_after.isdigit()) else (6 * (attempt + 1))
                add_log(f"Límite 429 detectado. Reintentando en {sleep_seconds}s...")
                time.sleep(sleep_seconds)
                continue
                
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise e
            
    raise Exception(f"No se pudo consultar {url} después de {max_attempts} intentos.")

def sanitize_filename(title):
    if title.lower().startswith("file:"):
        title = title[5:]
    sanitized = re.sub(r'[\\/*?:"<>|]', '_', title)
    sanitized = sanitized.replace(' ', '_')
    sanitized = re.sub(r'_{2,}', '_', sanitized)
    return sanitized.strip('_')

def map_families_to_categories():
    """Parses b:\\W\\categorias to resolve the exact Commons categories names."""
    archivo_categorias = "categorias"
    patron_of = r"Botanical illustrations of ([A-Z][a-z]+)"
    patron_prefijo = r"([A-Z][a-z]+) \(?botanical illustrations"
    
    mapping = {}
    if not os.path.exists(archivo_categorias):
        return mapping
        
    with open(archivo_categorias, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            category_part = re.sub(r"\s*\(\d+\s*[^)]*\)", "", linea).strip()
            if not category_part or len(category_part) <= 2 or "Subcategories" in category_part or "total" in category_part:
                continue
                
            match_of = re.search(patron_of, category_part, re.IGNORECASE)
            match_pref = re.search(patron_prefijo, category_part, re.IGNORECASE)
            
            family_name = None
            commons_cat = category_part
            if match_of:
                family_name = match_of.group(1).capitalize()
            elif match_pref:
                family_name = match_pref.group(1).capitalize()
            else:
                words = category_part.split()
                if words and words[0][0].isupper() and len(words[0]) > 3 and words[0].isalpha():
                    family_name = words[0].capitalize()
                    commons_cat = family_name

            if family_name and not family_name.lower().endswith(('phyceae', 'phyta')):
                if family_name not in mapping or "botanical" in commons_cat.lower():
                    mapping[family_name] = commons_cat
                
    return mapping

# Recursive category tree builder
def build_category_tree(cat_name, depth, max_depth, user_agent, files_out_list, visited=None, log_fn=None):
    """DFS traversal to list files and build a tree structure of categories."""
    if visited is None:
        visited = set()
        
    if cat_name in visited or depth > max_depth:
        return None
        
    visited.add(cat_name)
    
    def local_log(msg):
        if log_fn:
            log_fn(msg)
        else:
            add_log(msg)
            
    local_log(f"Explorando categoría: Category:{cat_name} (Nivel {depth})")
    
    api_url = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": user_agent}
    
    node = {
        "name": cat_name,
        "depth": depth,
        "files_count": 0,
        "children": []
    }
    
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{cat_name}",
        "cmlimit": "250",
        "format": "json"
    }
    
    has_more = True
    next_continue = {}
    
    direct_files = []
    subcats = []
    
    while has_more:
        req_params = params.copy()
        req_params.update(next_continue)
        
        try:
            resp = rate_limited_request(api_url, headers=headers, params=req_params)
            data = resp.json()
        except Exception as e:
            local_log(f"Error al listar Category:{cat_name}: {e}")
            break
            
        if "query" in data and "categorymembers" in data["query"]:
            for member in data["query"]["categorymembers"]:
                ns = member["ns"]
                title = member["title"]
                
                if ns == 6: # File
                    direct_files.append({
                        "pageid": member["pageid"],
                        "title": title,
                        "category": cat_name
                    })
                elif ns == 14: # Category
                    subcat_name = title[9:] if title.startswith("Category:") else title
                    if not any(x in subcat_name.lower() for x in ["herbarium", "specimen", "distribution", "maps"]):
                        subcats.append(subcat_name)
                        
        if "continue" in data:
            next_continue = data["continue"]
        else:
            has_more = False
            
    # Add files to the output collection list
    files_out_list.extend(direct_files)
    node["files_count"] = len(direct_files)
    
    local_log(f" -> Category:{cat_name}: Encontrados {len(direct_files)} archivos de imagen y {len(subcats)} subcategorías.")
    
    # Process children subcategories
    for subcat in subcats:
        child_node = build_category_tree(subcat, depth + 1, max_depth, user_agent, files_out_list, visited, log_fn)
        if child_node:
            node["children"].append(child_node)
            
    return node

def fetch_file_details(file_titles, user_agent):
    """Resolves raw URLs and description urls for a list of file titles."""
    api_url = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": user_agent}
    
    file_details = []
    batch_size = 50
    for i in range(0, len(file_titles), batch_size):
        batch = file_titles[i:i+batch_size]
        titles_param = "|".join(batch)
        
        params = {
            "action": "query",
            "titles": titles_param,
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "format": "json"
        }
        
        try:
            resp = rate_limited_request(api_url, headers=headers, params=params)
            data = resp.json()
            
            if "query" in data and "pages" in data["query"]:
                for page_id, page_data in data["query"]["pages"].items():
                    title = page_data["title"]
                    if "imageinfo" in page_data and len(page_data["imageinfo"]) > 0:
                        image_info = page_data["imageinfo"][0]
                        desc_url = image_info.get("descriptionurl")
                        if not desc_url:
                            safe_title = title.replace(" ", "_")
                            desc_url = f"https://commons.wikimedia.org/wiki/{safe_title}"
                            
                        file_details.append({
                            "title": title,
                            "image_url": image_info["url"],
                            "description_url": desc_url,
                            "size": image_info.get("size", 0),
                            "mime": image_info.get("mime", "")
                        })
        except Exception as e:
            add_log(f"Error al obtener detalles de lote: {e}")
            
    return file_details

def clean_botanical_category_title(category_name, family_cap):
    """
    Normalizes all Wikimedia Commons category naming conventions:
    - 'Category:Botanical illustrations of X' -> 'X'
    - 'Category:Illustrations of X' -> 'X'
    - 'Category:X - botanical illustrations' -> 'X'
    - 'Category:X (botanical illustrations)' -> 'X'
    - 'Category:X (illustrations)' -> 'X'
    - 'Category:X - illustrations' -> 'X'
    """
    if not category_name:
        return ""
        
    clean = category_name.strip()
    if clean.startswith("Category:"):
        clean = clean[9:].strip()
        
    # Remove leading prefix patterns
    prefixes = [
        r"^botanical\s+illustrations\s+of\s+",
        r"^illustrations\s+of\s+",
        r"^botanical\s+drawings\s+of\s+",
        r"^botanical\s+plates\s+of\s+"
    ]
    for p in prefixes:
        clean = re.sub(p, "", clean, flags=re.IGNORECASE).strip()
        
    # Remove trailing suffix patterns
    suffixes = [
        r"\s*-\s*botanical\s+illustrations$",
        r"\s*-\s*illustrations$",
        r"\s*\(botanical\s+illustrations\)$",
        r"\s*\(illustrations\)$",
        r"\s+botanical\s+illustrations$"
    ]
    for s in suffixes:
        clean = re.sub(s, "", clean, flags=re.IGNORECASE).strip()
        
    return clean

def get_category_folder_path(category_name, family_dir, family_cap):
    if not category_name:
        return family_dir
        
    taxon = clean_botanical_category_title(category_name, family_cap)
    
    if not taxon or taxon.lower() == family_cap.lower():
        return family_dir
        
    if taxon.lower().startswith("unidentified"):
        parts = taxon.split()
        if len(parts) >= 2:
            genus = parts[1].capitalize()
            if genus.lower() == family_cap.lower():
                return family_dir / "Unidentified"
            return family_dir / genus / "Unidentified"
        return family_dir / "Unidentified"
        
    parts = taxon.split()
    if len(parts) == 1:
        genus = parts[0].capitalize()
        return family_dir / genus
    elif len(parts) >= 2:
        genus = parts[0].capitalize()
        species = f"{genus} {parts[1].lower()}"
        return family_dir / genus / species
        
    return family_dir

def classify_taxon(category_name, family_cap):
    """Parse a Wikimedia Commons category name into structured taxon metadata."""
    if not category_name:
        return {"level": "family", "genus": None, "species": None, "display": family_cap}
    
    taxon = clean_botanical_category_title(category_name, family_cap)
    
    if not taxon or taxon.lower() == family_cap.lower():
        return {"level": "family", "genus": None, "species": None, "display": family_cap}
    
    # Unidentified family: "Unidentified Asteraceae"
    if taxon.lower() == f"unidentified {family_cap.lower()}":
        return {"level": "unidentified", "genus": None, "species": None, "display": f"Unidentified {family_cap}"}
    
    # Unidentified genus: "Unidentified Achillea"
    if taxon.lower().startswith("unidentified"):
        parts = taxon.split()
        if len(parts) >= 2:
            genus = parts[1].capitalize()
            if genus.lower() == family_cap.lower():
                return {"level": "unidentified", "genus": None, "species": None, "display": f"Unidentified {family_cap}"}
            return {"level": "unidentified", "genus": genus, "species": None, "display": f"Unidentified {genus}"}
        return {"level": "unidentified", "genus": None, "species": None, "display": "Unidentified"}
    
    parts = taxon.split()
    
    # Genus only: "Acanthus" or "Achillea"
    if len(parts) == 1:
        return {"level": "genus", "genus": parts[0].capitalize(), "species": None, "display": parts[0].capitalize()}
    
    # Check for variety/subspecies: "Achillea millefolium var. something"
    if len(parts) >= 4 and parts[2].lower() in ("var.", "subsp.", "f.", "ssp."):
        genus = parts[0].capitalize()
        species = f"{genus} {parts[1].lower()}"
        variety = " ".join(parts[2:])
        return {
            "level": "variety", 
            "genus": genus, 
            "species": species, 
            "variety": variety,
            "display": f"{species} {variety}"
        }
    
    # Species: "Achillea millefolium"
    if len(parts) >= 2:
        genus = parts[0].capitalize()
        species = f"{genus} {' '.join(parts[1:]).lower()}"
        return {"level": "species", "genus": genus, "species": species, "display": species}
    
    return {"level": "family", "genus": None, "species": None, "display": family_cap}

def download_worker(item, family_dir, user_agent, cancel_event):
    """Worker downloading a single item. Listens to cancel_event."""
    if cancel_event.is_set():
        return item["title"], False, "Canceled"
        
    headers = {"User-Agent": user_agent}
    
    image_url = item.get("image_url")
    if not image_url:
        return item["title"], False, "Missing image URL"
        
    _, ext = os.path.splitext(image_url.split('?')[0])
    if not ext:
        ext = ".jpg"
        
    base_name = sanitize_filename(item["title"])
    if not base_name:
        return item["title"], False, "Sanitization failed"
        
    if base_name.lower().endswith(ext.lower()):
        base_name = base_name[:-len(ext)]
        
    image_filename = base_name + ext
    
    # Resolve category-specific genus/species folder
    family_name = family_dir.name
    category = item.get("category", "")
    target_dir = get_category_folder_path(category, family_dir, family_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    image_path = os.path.join(target_dir, image_filename)
    
    # Download Image file
    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
        return item["title"], True, "Already exists"
        
    try:
        resp = rate_limited_request(image_url, headers=headers, stream=True, timeout=30)
        with open(image_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if cancel_event.is_set():
                    f.close()
                    try:
                        os.remove(image_path)
                    except:
                        pass
                    return item["title"], False, "Canceled"
                if chunk:
                    f.write(chunk)
        return item["title"], True, "Success"
    except Exception as e:
        if os.path.exists(image_path):
            try:
                os.remove(image_path)
            except:
                pass
        return item["title"], False, f"Image Error: {e}"

def run_download_thread(family, family_dir, files_list, progress, cancel_event, threads):
    """Background thread running the loop of thread-pool downloads."""
    log_file_path = family_dir / "download.log"
    try:
        log_file = open(log_file_path, "w", encoding="utf-8")
    except:
        log_file = None
        
    def log_fn(message):
        formatted = f"[{time.strftime('%H:%M:%S')}] {message}"
        if log_file:
            try:
                log_file.write(formatted + "\n")
                log_file.flush()
            except:
                pass
        add_log(message)
 
    log_fn(f"Iniciando descargas en segundo plano para {family}...")
    
    # Filter files that are already completed
    pending_items = []
    for item in files_list:
        title = item["title"]
        category = item.get("category", "")
        target_dir = get_category_folder_path(category, family_dir, family)
        
        if progress.get(title) == "completed":
            base_name = sanitize_filename(title)
            _, ext = os.path.splitext(title)
            if not ext:
                ext = ".jpg"
            if base_name.lower().endswith(ext.lower()):
                base_name = base_name[:-len(ext)]
            if os.path.exists(os.path.join(target_dir, base_name + ext)):
                continue
        pending_items.append(item)
        
    task_info = active_tasks[family]
    task_info["total"] = len(files_list)
    task_info["completed"] = len(files_list) - len(pending_items)
    task_info["errors"] = 0
    
    progress_json_path = os.path.join(family_dir, "progress.json")
    
    if len(pending_items) == 0:
        log_fn(f"¡Todos los archivos de {family} ya estaban completados!")
        task_info["status"] = "finished"
        if log_file:
            log_file.close()
        return
        
    # Resolve details (URLs) dynamically just-in-time
    log_fn(f"Resolviendo URLs JIT en lote para {len(pending_items)} archivos...")
    pending_titles = [x["title"] for x in pending_items]
    resolved_details = fetch_file_details(pending_titles, DEFAULT_USER_AGENT)
    
    details_map = {x["title"]: x for x in resolved_details}
    
    pending_resolved = []
    for item in pending_items:
        title = item["title"]
        if title in details_map:
            item.update(details_map[title])
            pending_resolved.append(item)
        else:
            task_info["errors"] += 1
            progress[title] = "error: No se pudieron obtener metadatos"
            log_fn(f"[ERROR] Metadatos fallidos para: {title}")
            
    if len(pending_resolved) == 0:
        log_fn(f"No hay archivos válidos para descargar en {family}.")
        task_info["status"] = "finished"
        if log_file:
            log_file.close()
        return
        
    try:
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {executor.submit(download_worker, item, family_dir, DEFAULT_USER_AGENT, cancel_event): item for item in pending_resolved}
            
            for future in as_completed(futures):
                if cancel_event.is_set():
                    log_fn(f"Descargas de {family} pausadas por el usuario.")
                    break
                    
                item = futures[future]
                title, success, msg = future.result()
                
                if success:
                    task_info["completed"] += 1
                    progress[title] = "completed"
                    pct = (task_info["completed"] / task_info["total"]) * 100
                    log_fn(f"[{task_info['completed']}/{task_info['total']}] ({pct:.1f}%) [OK] {title}")
                else:
                    if msg == "Canceled":
                        continue
                    task_info["errors"] += 1
                    progress[title] = f"error: {msg}"
                    log_fn(f"[ERROR] {title}: {msg}")
                    
                if (task_info["completed"] + task_info["errors"]) % 5 == 0:
                    with open(progress_json_path, "w", encoding="utf-8") as f:
                        json.dump(progress, f, indent=2, ensure_ascii=False)
                        
    except Exception as e:
        log_fn(f"Error crítico en hilo de descarga de {family}: {e}")
    finally:
        with open(progress_json_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
            
        if cancel_event.is_set():
            task_info["status"] = "paused"
        else:
            task_info["status"] = "finished"
            log_fn(f"Descargas finalizadas para {family}. Éxito: {task_info['completed']}, Errores: {task_info['errors']}")
            
        if log_file:
            try:
                log_file.close()
            except:
                pass

def run_scan_thread(family_cap, family_dir, commons_category, depth):
    active_scans[family_cap] = {
        "status": "running",
        "tree": None,
        "files_count": 0,
        "error": None
    }
    
    log_file_path = family_dir / "scan.log"
    
    try:
        with open(log_file_path, "w", encoding="utf-8") as log_file:
            def log_fn(message):
                formatted = f"[{time.strftime('%H:%M:%S')}] {message}"
                log_file.write(formatted + "\n")
                log_file.flush()
                add_log(message)
                
            checkpoint_file = family_dir / "scan_checkpoint.json"
            log_fn(f"Iniciando escaneo Pywikibot para {family_cap} (depth={depth})...")
            
            tree, files_out = pywikibot_crawler.explore_hierarchy(commons_category, max_depth=depth, log_fn=log_fn, checkpoint_path=checkpoint_file)
            
            if not files_out:
                log_fn(f"No se encontraron archivos en el escaneo de {family_cap}")
                active_scans[family_cap] = {
                    "status": "completed",
                    "tree": tree,
                    "files_count": 0,
                    "error": None
                }
                return
                
            # Save files list cache
            files_json_path = family_dir / "files_list.json"
            with open(files_json_path, "w", encoding="utf-8") as f:
                json.dump(files_out, f, indent=2, ensure_ascii=False)
                
            log_fn(f"Escaneo de {family_cap} completado. {len(files_out)} archivos guardados en cache.")
            
            # Save category tree
            with open(family_dir / "category_tree.json", "w", encoding="utf-8") as f:
                json.dump(tree, f, indent=2, ensure_ascii=False)
                
            active_scans[family_cap] = {
                "status": "completed",
                "tree": tree,
                "files_count": len(files_out),
                "error": None
            }
            
            # Update global consolidated status for this family
            local_count = len([x for x in family_dir.iterdir() if x.is_file() and x.suffix.lower() not in ('.html', '.json', '.log')])
            commons_count = len(files_out)
            prog = round((local_count / commons_count) * 100, 1) if commons_count > 0 else 0.0
            
            with global_status_lock:
                global_status = load_global_status()
                global_status[family_cap] = {
                    "scanned": True,
                    "commons_files": commons_count,
                    "local_files": local_count,
                    "progress": prog,
                    "last_scan": time.strftime("%Y-%m-%d %H:%M")
                }
                with open(global_status_path, "w", encoding="utf-8") as f_glob:
                    json.dump(global_status, f_glob, indent=2, ensure_ascii=False)
            
    except Exception as e:
        error_msg = f"Escaneo fallido: {e}"
        add_log(f"Error en escaneo de {family_cap}: {e}")
        try:
            with open(log_file_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{time.strftime('%H:%M:%S')}] [ERROR] {error_msg}\n")
        except:
            pass
            
        active_scans[family_cap] = {
            "status": "failed",
            "tree": None,
            "files_count": 0,
            "error": str(e)
        }

active_batch_scan = {
    "active": False,
    "cancel_event": None,
    "current_family": "",
    "processed": 0,
    "total": 0
}

def run_batch_scan_thread(depth, cancel_event):
    global active_batch_scan
    
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    if not index_json_path.exists():
        add_log("[LOTE ERROR] No se encontró el índice de familias.")
        active_batch_scan["active"] = False
        return
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    families_list = sorted(list(families_map.keys()))
    
    # Filter pending (unscanned)
    global_status = get_consolidated_status()
    pending_families = []
    for name in families_list:
        if not global_status.get(name, {}).get("scanned"):
            pending_families.append(name)
            
    if not pending_families:
        add_log("[LOTE] Todas las familias de la colección ya se encuentran escaneadas.")
        active_batch_scan["active"] = False
        return
        
    active_batch_scan["total"] = len(pending_families)
    active_batch_scan["processed"] = 0
    
    add_log(f"[LOTE INICIO] Escaneando {len(pending_families)} familias pendientes (Profundidad={depth})...")
    
    for idx, family_name in enumerate(pending_families):
        if cancel_event.is_set():
            add_log("[LOTE CANCELADO] Escaneo por lotes detenido por el usuario.")
            break
            
        active_batch_scan["current_family"] = family_name
        active_batch_scan["processed"] = idx
        
        family_dir = Path(families_map[family_name])
        family_dir.mkdir(parents=True, exist_ok=True)
        
        # Dynamically resolve exact botanical illustration category (e.g. Botanical illustrations of <Family>)
        commons_category = resolve_commons_category(family_name)
        log_file_path = family_dir / "scan.log"
        
        try:
            with open(log_file_path, "w", encoding="utf-8") as log_file:
                def log_fn(message):
                    formatted = f"[{time.strftime('%H:%M:%S')}] {message}"
                    log_file.write(formatted + "\n")
                    log_file.flush()
                    try:
                        with open(BATCH_LOG_PATH, "a", encoding="utf-8") as bf:
                            bf.write(f"[{family_name}] {formatted}\n")
                    except:
                        pass
                    add_log(f"[{family_name}] {message}")
                    
                checkpoint_file = family_dir / "scan_checkpoint.json"
                log_fn(f"Iniciando escaneo Pywikibot en lote para {family_name} -> Category:{commons_category} (depth={depth})...")
                tree, files_out = pywikibot_crawler.explore_hierarchy(
                    commons_category, 
                    max_depth=depth, 
                    log_fn=log_fn, 
                    checkpoint_path=checkpoint_file, 
                    cancel_event=cancel_event
                )
                
                if cancel_event.is_set():
                    log_fn(f"Escaneo de {family_name} cancelado.")
                    active_scans[family_name] = {"status": "failed", "tree": None, "files_count": 0, "error": "Canceled"}
                    break
                    
                files_json_path = family_dir / "files_list.json"
                tree_json_path = family_dir / "category_tree.json"
                
                if not files_out:
                    log_fn(f"No se encontraron imágenes para {family_name}.")
                    active_scans[family_name] = {
                        "status": "completed",
                        "tree": tree,
                        "files_count": 0,
                        "error": None
                    }
                else:
                    # Save files_list.json atomically
                    temp_files = str(files_json_path) + ".tmp"
                    with open(temp_files, "w", encoding="utf-8") as f:
                        json.dump(files_out, f, indent=2, ensure_ascii=False)
                    safe_atomic_replace(temp_files, str(files_json_path))
                    
                    # Save category_tree.json atomically
                    temp_tree = str(tree_json_path) + ".tmp"
                    with open(temp_tree, "w", encoding="utf-8") as f:
                        json.dump(tree, f, indent=2, ensure_ascii=False)
                    safe_atomic_replace(temp_tree, str(tree_json_path))
                    
                    log_fn(f"Escaneo de {family_name} finalizado: {len(files_out)} ilustraciones registradas.")
                    
                    active_scans[family_name] = {
                        "status": "completed",
                        "tree": tree,
                        "files_count": len(files_out),
                        "error": None
                    }
                    
                # Update consolidated global status atomically
                local_count = len([x for x in family_dir.iterdir() if x.is_file() and x.suffix.lower() not in ('.html', '.json', '.log')])
                commons_count = len(files_out) if files_out else 0
                prog = round((local_count / commons_count) * 100, 1) if commons_count > 0 else 0.0
                
                with global_status_lock:
                    global_status = load_global_status()
                    global_status[family_name] = {
                        "scanned": True,
                        "commons_files": commons_count,
                        "local_files": local_count,
                        "progress": prog,
                        "last_scan": time.strftime("%Y-%m-%d %H:%M")
                    }
                    save_global_status(global_status)
                    
        except Exception as e:
            add_log(f"[LOTE ERROR] Falló {family_name}: {e}")
            active_scans[family_name] = {
                "status": "failed",
                "tree": None,
                "files_count": 0,
                "error": str(e)
            }
            
        active_batch_scan["processed"] = idx + 1
        time.sleep(1.5)
        
    add_log(f"[LOTE FIN] Escaneo por lotes completado ({active_batch_scan['processed']} de {active_batch_scan['total']} familias).")
    active_batch_scan["active"] = False

# Server Endpoints
@app.route("/")
def index():
    return render_template("index.html")

_families_cache = {"timestamp": 0, "data": []}

@app.route("/api/families")
def get_families():
    global _families_cache
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    if not index_json_path.exists():
        return jsonify({"error": "No families index found. Run organizar_familias.py."}), 404
        
    now = time.time()
    # Serve cached list if less than 15 seconds old to prevent disk I/O lock contention
    if now - _families_cache["timestamp"] < 15.0 and _families_cache["data"]:
        results = []
        for item in _families_cache["data"]:
            item_copy = dict(item)
            item_copy["status"] = active_tasks.get(item["name"], {}).get("status", "idle")
            results.append(item_copy)
        return jsonify(results)
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    # Count files physically downloaded in each folder
    results = []
    for name, path_str in sorted(families_map.items()):
        path = Path(path_str)
        downloaded = 0
        if path.exists():
            # Count only image files (.jpg, .png, etc.), not HTML and not JSON
            downloaded = len([x for x in path.iterdir() if x.is_file() and x.suffix.lower() not in ('.html', '.json', '.log')])
            
        results.append({
            "name": name,
            "path": str(path),
            "downloaded": downloaded,
            "status": active_tasks.get(name, {}).get("status", "idle")
        })
        
    _families_cache = {"timestamp": now, "data": results}
    return jsonify(results)

def resolve_commons_category(family):
    """Dynamically resolves the exact botanical illustration Commons category for a family."""
    url = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    
    candidates = [
        f"Category:Botanical illustrations of {family}",
        f"Category:{family} - botanical illustrations",
        f"Category:{family}"
    ]
    
    params = {"action": "query", "titles": "|".join(candidates), "format": "json"}
    try:
        res = rate_limited_request(url, headers=headers, params=params, timeout=10).json()
        pages = res.get("query", {}).get("pages", {})
        
        found = {}
        for pid, pdata in pages.items():
            if int(pid) > 0:
                found[pdata["title"]] = pdata["pageid"]
                
        for cand in candidates:
            if cand in found:
                return cand[9:] if cand.startswith("Category:") else cand
    except Exception as e:
        print(f"Error resolving Commons category for {family}: {e}")
        
    return family

@app.route("/api/scan/<family>", methods=["POST"])
def scan_family(family):
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    if not index_json_path.exists():
        return jsonify({"error": "No index found"}), 404
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Family not found in index"}), 404
        
    # Check if already scanning
    if family_cap in active_scans and active_scans[family_cap]["status"] == "running":
        return jsonify({"status": "already scanning"})
        
    family_dir = Path(families_map[family_cap])
    family_dir.mkdir(parents=True, exist_ok=True)
    
    # Resolve exact Commons category (e.g. Botanical illustrations of Asteraceae)
    commons_category = resolve_commons_category(family_cap)
    req_data = request.get_json(silent=True) or {}
    depth = req_data.get("depth", 3)
    
    # Spawn scan in background thread
    thread = threading.Thread(target=run_scan_thread, args=(
        family_cap, family_dir, commons_category, depth
    ))
    thread.start()
    
    return jsonify({"status": "started"})

@app.route("/api/files/<family>")
def get_family_files(family):
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Family not found"}), 404
        
    family_dir = Path(families_map[family_cap])
    files_json_path = family_dir / "files_list.json"
    progress_json_path = family_dir / "progress.json"
    
    # Check if Wikipedia article exists
    has_wikipedia = (family_dir / "wikipedia_article.html").exists()
    wikipedia_url = f"/api/image/{family_cap}/wikipedia_article.html" if has_wikipedia else None

    files_list = []
    if files_json_path.exists():
        try:
            with open(files_json_path, "r", encoding="utf-8") as f:
                files_list = json.load(f)
        except Exception as e:
            ckpt_path = family_dir / "scan_checkpoint.json"
            if ckpt_path.exists():
                try:
                    with open(ckpt_path, "r", encoding="utf-8") as f:
                        files_list = json.load(f).get("all_files", [])
                except:
                    pass
    elif (family_dir / "scan_checkpoint.json").exists():
        try:
            with open(family_dir / "scan_checkpoint.json", "r", encoding="utf-8") as f:
                files_list = json.load(f).get("all_files", [])
        except:
            pass

    if not files_list:
        return jsonify({"scanned": False, "files": [], "wikipedia_url": wikipedia_url})
        
    progress = {}
    if progress_json_path.exists() and progress_json_path.stat().st_size > 0:
        try:
            with open(progress_json_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
        except:
            pass
            
    # Index all physical files on disk in family_dir for instant lookup
    disk_files_set = set()
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        for f in files:
            disk_files_set.add(f.lower())

    scanned_titles_sanitized = set()

    # Augment details with current status
    for item in files_list:
        title = item["title"]
        category = item.get("category", "")
        base_name = sanitize_filename(title)
        
        # Parse extension directly from file title
        _, ext = os.path.splitext(title)
        if not ext:
            ext = ".jpg"
            
        if base_name.lower().endswith(ext.lower()):
            base_name = base_name[:-len(ext)]
            
        filename_to_check = (base_name + ext).lower()
        scanned_titles_sanitized.add(filename_to_check)
        has_image = filename_to_check in disk_files_set
        
        if has_image:
            item["status"] = "completed"
        elif progress.get(title) and progress.get(title).startswith("error:"):
            item["status"] = "error"
            item["error_msg"] = progress[title]
        else:
            item["status"] = "pending"
        
        # Add taxon classification metadata
        taxon = classify_taxon(category, family_cap)
        item["taxon"] = taxon

    # Ensure all physical files on disk are present in files_list
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff', '.pdf', '.webp'):
                if f.lower() not in scanned_titles_sanitized:
                    scanned_titles_sanitized.add(f.lower())
                    files_list.append({
                        "title": f"File:{f}",
                        "category": family_cap,
                        "status": "completed",
                        "taxon": classify_taxon(family_cap, family_cap)
                    })
            
    # Load category tree if exists
    tree = None
    tree_json_path = family_dir / "category_tree.json"
    if tree_json_path.exists():
        try:
            with open(tree_json_path, "r", encoding="utf-8") as f:
                tree = json.load(f)
        except:
            pass
            
    # Check if Wikipedia article exists
    has_wikipedia = (family_dir / "wikipedia_article.html").exists()
    wikipedia_url = f"/api/image/{family_cap}/wikipedia_article.html" if has_wikipedia else None
            
    return jsonify({
        "scanned": True,
        "files": files_list,
        "tree": tree,
        "wikipedia_url": wikipedia_url
    })

@app.route("/api/download/<family>", methods=["POST"])
def start_download(family):
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Family not found"}), 404
        
    family_dir = Path(families_map[family_cap])
    files_json_path = family_dir / "files_list.json"
    
    if not files_json_path.exists():
        return jsonify({"error": "Please scan the category first"}), 400
        
    # Check if already running
    if family_cap in active_tasks and active_tasks[family_cap]["status"] == "running":
        return jsonify({"status": "already running"})
        
    with open(files_json_path, "r", encoding="utf-8") as f:
        files_list = json.load(f)
        
    # Load progress
    progress_json_path = family_dir / "progress.json"
    progress = {}
    if progress_json_path.exists():
        try:
            with open(progress_json_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
        except:
            pass
            
    cancel_event = threading.Event()
    threads = request.json.get("threads", 3)
    
    # Spawn background worker thread
    thread = threading.Thread(target=run_download_thread, args=(
        family_cap, family_dir, files_list, progress, cancel_event, threads
    ))
    
    active_tasks[family_cap] = {
        "thread": thread,
        "cancel_event": cancel_event,
        "status": "running",
        "total": len(files_list),
        "completed": 0,
        "errors": 0
    }
    
    thread.start()
    return jsonify({"status": "started"})

@app.route("/api/pause/<family>", methods=["POST"])
def pause_download(family):
    family_cap = family.capitalize()
    if family_cap in active_tasks and active_tasks[family_cap]["status"] == "running":
        active_tasks[family_cap]["cancel_event"].set()
        active_tasks[family_cap]["status"] = "paused"
        add_log(f"Enviada señal de pausa para {family_cap}...")
        return jsonify({"status": "pausing"})
    return jsonify({"status": "not running"})

@app.route("/api/status")
def get_status():
    status_list = []
    for name, task in active_tasks.items():
        status_list.append({
            "family": name,
            "status": task["status"],
            "total": task["total"],
            "completed": task["completed"],
            "errors": task["errors"]
        })
        
    since_id = request.args.get("since_id", 0, type=int)
    
    with logs_lock:
        if since_id > 0:
            logs_slice = [x for x in recent_logs if x["id"] > since_id]
        else:
            logs_slice = list(recent_logs)
            
    scans_status = {}
    for name, scan in active_scans.items():
        scans_status[name] = {
            "status": scan["status"],
            "files_count": scan["files_count"],
            "error": scan.get("error")
        }
        
    return jsonify({
        "tasks": status_list,
        "logs": logs_slice,
        "scans": scans_status,
        "batch_scan": {
            "active": active_batch_scan["active"],
            "current_family": active_batch_scan["current_family"],
            "processed": active_batch_scan["processed"],
            "total": active_batch_scan["total"]
        }
    })

_GLOBAL_STATUS_TTL = 20  # seconds

@app.route("/api/global-status")
def get_global_status():
    now = time.time()
    if _global_status_cache["data"] is not None and (now - _global_status_cache["ts"]) < _GLOBAL_STATUS_TTL:
        return jsonify(_global_status_cache["data"])
    status = get_consolidated_status()
    _global_status_cache["data"] = status
    _global_status_cache["ts"] = now
    return jsonify(status)

@app.route("/api/batch-scan", methods=["POST"])
def start_batch_scan():
    global active_batch_scan
    if active_batch_scan["active"]:
        return jsonify({"status": "already running"})
        
    depth = request.json.get("depth", 0)
    cancel_event = threading.Event()
    
    active_batch_scan["active"] = True
    active_batch_scan["cancel_event"] = cancel_event
    active_batch_scan["current_family"] = ""
    active_batch_scan["processed"] = 0
    active_batch_scan["total"] = 0
    
    thread = threading.Thread(target=run_batch_scan_thread, args=(depth, cancel_event))
    thread.start()
    
    return jsonify({"status": "started"})

@app.route("/api/batch-scan/stop", methods=["POST"])
def stop_batch_scan():
    global active_batch_scan
    if active_batch_scan["active"] and active_batch_scan["cancel_event"]:
        active_batch_scan["cancel_event"].set()
        active_batch_scan["active"] = False
        add_log("[LOTE] Enviada señal de parada para el escaneo de lote...")
        return jsonify({"status": "stopping"})
    return jsonify({"status": "not running"})

def fetch_wikipedia_article(name, family_dir):
    """Queries Wikipedia API for the page, cleans the HTML content, styles it, and saves it."""
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    
    # Try Spanish Wikipedia first
    api_url_es = "https://es.wikipedia.org/w/api.php"
    params_es = {
        "action": "parse",
        "page": name,
        "prop": "text",
        "format": "json",
        "redirects": "1"
    }
    
    html_content = ""
    lang = "es"
    try:
        resp = requests.get(api_url_es, headers=headers, params=params_es, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "parse" in data and "text" in data["parse"]:
            html_content = data["parse"]["text"]["*"]
            lang = "es"
    except Exception as e:
        print(f"No se encontró en es.wikipedia: {e}")
        
    # If not found, try English Wikipedia
    if not html_content:
        api_url_en = "https://en.wikipedia.org/w/api.php"
        params_en = {
            "action": "parse",
            "page": name,
            "prop": "text",
            "format": "json",
            "redirects": "1"
        }
        try:
            resp = requests.get(api_url_en, headers=headers, params=params_en, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if "parse" in data and "text" in data["parse"]:
                html_content = data["parse"]["text"]["*"]
                lang = "en"
        except Exception as e:
            print(f"No se encontró en en.wikipedia: {e}")
            
    if not html_content:
        raise Exception(f"No se encontró artículo en Wikipedia para '{name}'.")
        
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Clean unwanted classes and templates
    for el in soup.find_all(class_=[
        "mw-empty-elt", "mw-editsection", "ambox", "navbox", "catlinks",
        "metadata", "noprint", "reflist", "reference", "sisterproject",
        "mw-hidden-catlinks", "vertical-navbox", "infobox", "authority-control"
    ]):
        el.decompose()

    # Remove heavy sections: Bibliografía, Referencias, Enlaces externos
    SECTIONS_TO_REMOVE = [
        "referencias", "references", "bibliografía", "bibliografia", "bibliography",
        "enlaces_externos", "external_links", "further_reading", "lecturas_adicionales"
    ]
    
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = heading.get_text().lower().strip()
        span_elem = heading.find(id=True)
        span_id = span_elem["id"].lower().strip() if span_elem else ""
        
        remove_section = False
        for target in SECTIONS_TO_REMOVE:
            if target in heading_text or target in span_id:
                remove_section = True
                break
                
        if remove_section:
            siblings_to_remove = [heading]
            next_elem = heading.find_next_sibling()
            while next_elem and next_elem.name not in ["h1", "h2", "h3"]:
                siblings_to_remove.append(next_elem)
                next_elem = next_elem.find_next_sibling()
                
            for el in siblings_to_remove:
                el.decompose()
        
    # Fix links for internal iframe navigation without opening new browser windows
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href.startswith("/wiki/"):
            clean_term = href[6:].split("#")[0]
            if clean_term:
                a["href"] = "#"
                a["data-wiki-page"] = clean_term
                a["onclick"] = f"if(window.parent && window.parent.downloadWikipediaArticle){{window.parent.downloadWikipediaArticle('{clean_term}');}} return false;"
        elif href.startswith("#"):
            a.decompose()
            
    cleaned_html = str(soup)
    
    styled_article = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Wikipedia: {name}</title>
    <style>
        body {{
            background-color: #0b0f19;
            color: #f3f4f6;
            font-family: 'Inter', sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 32px;
            font-size: 15px;
        }}
        h1, h2, h3, h4 {{
            font-family: 'Outfit', sans-serif;
            color: #10b981;
            margin-top: 24px;
            margin-bottom: 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 6px;
        }}
        h1 {{ font-size: 26px; }}
        h2 {{ font-size: 20px; }}
        h3 {{ font-size: 16px; }}
        p {{ margin-bottom: 16px; color: #a0aec0; }}
        a {{ color: #10b981; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        ul, ol {{ margin-bottom: 16px; padding-left: 20px; color: #a0aec0; }}
        li {{ margin-bottom: 6px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 14px;
        }}
        th, td {{
            padding: 10px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            text-align: left;
        }}
        th {{ background-color: rgba(255, 255, 255, 0.03); color: #f3f4f6; }}
        .thumb {{
            float: right;
            margin: 0 0 20px 20px;
            background: rgba(22, 30, 49, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 10px;
            max-width: 250px;
        }}
        .thumbimage {{ max-width: 100%; height: auto; border-radius: 4px; }}
        .thumbcaption {{ font-size: 12px; color: #64748b; margin-top: 6px; text-align: center; }}
        .clear {{ clear: both; }}
    </style>
    <script>
        document.addEventListener('click', function(e) {{
            var a = e.target.closest('a');
            if (a) {{
                var href = a.getAttribute('href') || '';
                var wikiPage = a.getAttribute('data-wiki-page');
                if (!wikiPage && href.indexOf('/wiki/') !== -1) {{
                    wikiPage = href.split('/wiki/')[1].split('#')[0];
                }}
                if (wikiPage) {{
                    e.preventDefault();
                    e.stopPropagation();
                    var term = decodeURIComponent(wikiPage).replace(/_/g, ' ');
                    if (window.parent) {{
                        window.parent.postMessage({{ type: 'WIKI_NAVIGATE', term: term }}, '*');
                    }}
                }}
            }}
        }}, true);
    </script>
</head>

<body>
    <h1>{name} <span style="font-size: 12px; color: #64748b; font-weight: normal;">(Adaptado de Wikipedia)</span></h1>
    {cleaned_html}
</body>
</html>
"""
    
    article_path = family_dir / "wikipedia_article.html"
    with open(article_path, "w", encoding="utf-8") as f:
        f.write(styled_article)
        
    return str(article_path)

@app.route("/api/wikipedia/<family>", methods=["POST"])
def get_wikipedia_info(family):
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Family not found"}), 404
        
    family_dir = Path(families_map[family_cap])
    
    query = family_cap
    if request.json and request.json.get("query"):
        query = request.json.get("query")
        
    try:
        article_path = fetch_wikipedia_article(query, family_dir)
        return jsonify({
            "status": "success",
            "article_url": f"/api/image/{family_cap}/wikipedia_article.html"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/log")
def get_app_log():
    log_type = request.args.get("type", "app")
    target_path = BATCH_LOG_PATH if log_type == "batch" else APP_LOG_PATH
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            return Response(content, mimetype="text/plain; charset=utf-8")
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return "Sin registros grabados aún.", 200

@app.route("/api/image/<family>/<filename>")
def serve_image(family, filename):
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return "Family not found", 404
        
    family_dir = Path(families_map[family_cap])
    
    # Locate original file recursively
    file_path = None
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        if filename in files:
            file_path = Path(root) / filename
            break
            
    if not file_path or not file_path.exists():
        return "File not found", 404
        
    # If TIFF, convert to web JPEG on the fly for web browser compatibility
    if file_path.suffix.lower() in ('.tiff', '.tif'):
        web_cache_path = family_dir / ".thumbnails" / (file_path.stem + "_full.jpg")
        if not web_cache_path.exists():
            try:
                from PIL import Image
                (family_dir / ".thumbnails").mkdir(parents=True, exist_ok=True)
                with Image.open(file_path) as img:
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.thumbnail((2560, 2560))
                    img.save(web_cache_path, "JPEG", quality=92)
            except Exception as e:
                print(f"TIFF web preview generation failed for {filename}: {e}")
        if web_cache_path.exists():
            return send_from_directory(family_dir / ".thumbnails", file_path.stem + "_full.jpg", mimetype="image/jpeg", max_age=31536000)
        
    return send_from_directory(file_path.parent, filename, max_age=31536000)

def generate_pdf_thumbnail(pdf_path, thumb_path, filename):
    """Generates a JPEG thumbnail for a PDF file using pypdf image extraction or Wikimedia Commons API fallback."""
    try:
        from pypdf import PdfReader
        from PIL import Image
        import io
        
        reader = PdfReader(str(pdf_path))
        if len(reader.pages) > 0 and len(reader.pages[0].images) > 0:
            img_data = reader.pages[0].images[0].data
            with Image.open(io.BytesIO(img_data)) as img:
                img.thumbnail((400, 400))
                if img.mode in ("RGBA", "P", "CMYK"):
                    img = img.convert("RGB")
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(thumb_path, "JPEG", quality=85)
                return True
    except Exception as e:
        print(f"pypdf extraction failed for {filename}: {e}")
        
    # Fallback to Wikimedia Commons API thumburl
    try:
        file_title = f"File:{filename}"
        api_url = "https://commons.wikimedia.org/w/api.php"
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        params = {
            "action": "query",
            "titles": file_title,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 400,
            "format": "json"
        }
        resp = rate_limited_request(api_url, headers=headers, params=params, timeout=15)
        data = resp.json()
        if "query" in data and "pages" in data["query"]:
            for page_id, page_data in data["query"]["pages"].items():
                if "imageinfo" in page_data and len(page_data["imageinfo"]) > 0:
                    thumb_url = page_data["imageinfo"][0].get("thumburl")
                    if thumb_url:
                        img_resp = requests.get(thumb_url, headers=headers, timeout=20)
                        if img_resp.status_code == 200:
                            thumb_path.parent.mkdir(parents=True, exist_ok=True)
                            with open(thumb_path, "wb") as f:
                                f.write(img_resp.content)
                            return True
    except Exception as e:
        print(f"Commons PDF thumbnail fallback failed for {filename}: {e}")
        
    return False

@app.route("/api/thumbnail/<family>/<filename>")
def serve_thumbnail(family, filename):
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return "Family not found", 404
        
    family_dir = Path(families_map[family_cap])
    
    # Locate original file recursively
    original_path = None
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        if filename in files:
            original_path = Path(root) / filename
            break
            
    if not original_path or not original_path.exists():
        return "File not found", 404
        
    if original_path.suffix.lower() in ('.html', '.json', '.log'):
        return send_from_directory(original_path.parent, filename)
        
    thumb_dir = family_dir / ".thumbnails"
    
    # Handle PDF thumbnails
    if original_path.suffix.lower() == '.pdf':
        pdf_thumb_name = filename + ".jpg"
        thumb_path = thumb_dir / pdf_thumb_name
        if not thumb_path.exists():
            generate_pdf_thumbnail(original_path, thumb_path, filename)
        if thumb_path.exists():
            return send_from_directory(thumb_dir, pdf_thumb_name, mimetype="image/jpeg", max_age=31536000)
        return send_from_directory(original_path.parent, filename, max_age=31536000)

    # Handle TIFF thumbnails
    if original_path.suffix.lower() in ('.tiff', '.tif'):
        tiff_thumb_name = original_path.stem + "_thumb.jpg"
        thumb_path = thumb_dir / tiff_thumb_name
        if not thumb_path.exists():
            try:
                from PIL import Image
                thumb_dir.mkdir(parents=True, exist_ok=True)
                with Image.open(original_path) as img:
                    img.thumbnail((350, 350))
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(thumb_path, "JPEG", quality=85)
            except Exception as e:
                print(f"TIFF thumbnail generation failed for {filename}: {e}")
        if thumb_path.exists():
            return send_from_directory(thumb_dir, tiff_thumb_name, mimetype="image/jpeg", max_age=31536000)

    thumb_path = thumb_dir / filename
    
    if not thumb_path.exists():
        try:
            from PIL import Image
            thumb_dir.mkdir(parents=True, exist_ok=True)
            with Image.open(original_path) as img:
                img.thumbnail((300, 300))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                elif img.mode == "CMYK":
                    img = img.convert("RGB")
                img.save(thumb_path, "JPEG", quality=85)
        except Exception as e:
            return send_from_directory(original_path.parent, filename, max_age=31536000)
            
    return send_from_directory(thumb_dir, filename, mimetype="image/jpeg", max_age=31536000)

# --- Album Management Endpoints ---
FAVORITES_JSON_PATH = COLLECTION_DIR / "favorites.json"
favorites_lock = threading.Lock()

def load_favorites():
    if not FAVORITES_JSON_PATH.exists():
        return {}
    try:
        with open(FAVORITES_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_favorites(favs):
    try:
        with open(FAVORITES_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(favs, f, indent=2, ensure_ascii=False)
    except:
        pass

@app.route("/api/album", methods=["GET"])
def get_album():
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    if not index_json_path.exists():
        return jsonify([])
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    favorites = load_favorites()
    album_items = []
    
    for family_name, path_str in families_map.items():
        family_dir = Path(path_str)
        if not family_dir.exists():
            continue
            
        media_files = []
        for root, dirs, files in os.walk(family_dir):
            if ".thumbnails" in root:
                continue
            for f_name in files:
                ext = os.path.splitext(f_name)[1].lower()
                if ext not in ('.html', '.json', '.log', '.txt'):
                    full_p = Path(root) / f_name
                    media_files.append((f_name, full_p))
                    
        if not media_files:
            continue
            
        metadata_map = {}
        files_json_path = family_dir / "files_list.json"
        if files_json_path.exists():
            try:
                with open(files_json_path, "r", encoding="utf-8") as f_meta:
                    files_list = json.load(f_meta)
                    for item in files_list:
                        title = item["title"]
                        base_name = sanitize_filename(title)
                        _, ext = os.path.splitext(title)
                        if not ext:
                            ext = ".jpg"
                        if base_name.lower().endswith(ext.lower()):
                            base_name = base_name[:-len(ext)]
                        filename = base_name + ext
                        metadata_map[filename.lower()] = item
            except:
                pass
                
        for fname, fpath in media_files:
            meta = metadata_map.get(fname.lower(), {})
            fav_key = f"{family_name}/{fname}"
            is_favorite = favorites.get(fav_key, False)
            
            category = meta.get("category", "")
            taxon = classify_taxon(category, family_name)
            
            album_items.append({
                "family": family_name,
                "filename": fname,
                "title": meta.get("title", f"File:{fname.replace('_', ' ')}"),
                "description_url": meta.get("description_url"),
                "favorite": is_favorite,
                "size": fpath.stat().st_size,
                "mime": "image/jpeg" if fname.lower().endswith(('.jpg', '.jpeg')) else "image/png",
                "taxon": taxon
            })
            
    return jsonify(album_items)

@app.route("/api/album/favorite", methods=["POST"])
def toggle_favorite():
    data = request.json or {}
    family = data.get("family")
    filename = data.get("filename")
    is_fav = data.get("favorite", False)
    
    if not family or not filename:
        return jsonify({"error": "Missing family or filename"}), 400
        
    fav_key = f"{family}/{filename}"
    with favorites_lock:
        favs = load_favorites()
        if is_fav:
            favs[fav_key] = True
        else:
            favs.pop(fav_key, None)
        save_favorites(favs)
        
    return jsonify({"status": "success", "favorite": is_fav})

@app.route("/api/album/delete", methods=["POST"])
def delete_album_file():
    data = request.json or {}
    family = data.get("family")
    filename = data.get("filename")
    
    if not family or not filename:
        return jsonify({"error": "Missing family or filename"}), 400
        
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Family not found"}), 404
        
    family_dir = Path(families_map[family_cap])
    
    # Locate recursively
    file_path = None
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        if filename in files:
            file_path = Path(root) / filename
            break
            
    if not file_path or not file_path.exists():
        return jsonify({"error": "File not found on disk"}), 404
        
    try:
        os.remove(file_path)
        
        # Remove thumbnail if any
        thumb_path = family_dir / ".thumbnails" / filename
        if thumb_path.exists():
            try:
                os.remove(thumb_path)
            except:
                pass
                
        fav_key = f"{family}/{filename}"
        with favorites_lock:
            favs = load_favorites()
            if fav_key in favs:
                favs.pop(fav_key, None)
                save_favorites(favs)
                
        progress_json_path = family_dir / "progress.json"
        if progress_json_path.exists():
            try:
                with open(progress_json_path, "r", encoding="utf-8") as f_prog:
                    progress = json.load(f_prog)
                files_json_path = family_dir / "files_list.json"
                if files_json_path.exists():
                    with open(files_json_path, "r", encoding="utf-8") as f_list:
                        files_list = json.load(f_list)
                    for item in files_list:
                        title = item["title"]
                        base_name = sanitize_filename(title)
                        _, ext = os.path.splitext(title)
                        if not ext:
                            ext = ".jpg"
                        if base_name.lower().endswith(ext.lower()):
                            base_name = base_name[:-len(ext)]
                        if (base_name + ext).lower() == filename.lower():
                            progress.pop(title, None)
                            break
                with open(progress_json_path, "w", encoding="utf-8") as f_prog:
                    json.dump(progress, f_prog, indent=2, ensure_ascii=False)
            except:
                pass
                
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": f"Failed to delete file: {e}"}), 500

@app.route("/api/album/rename", methods=["POST"])
def rename_album_file():
    data = request.json or {}
    family = data.get("family")
    filename = data.get("filename")
    new_filename = data.get("new_filename")
    
    if not family or not filename or not new_filename:
        return jsonify({"error": "Missing parameters"}), 400
        
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Family not found"}), 404
        
    family_dir = Path(families_map[family_cap])
    
    # Locate recursively
    old_path = None
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        if filename in files:
            old_path = Path(root) / filename
            break
            
    if not old_path or not old_path.exists():
        return jsonify({"error": "Source file not found"}), 404
        
    new_path = old_path.parent / new_filename
    if new_path.exists():
        return jsonify({"error": "Destination file already exists"}), 400
        
    try:
        os.rename(old_path, new_path)
        
        # Rename thumbnail if any
        old_thumb = family_dir / ".thumbnails" / filename
        new_thumb = family_dir / ".thumbnails" / new_filename
        if old_thumb.exists():
            try:
                os.rename(old_thumb, new_thumb)
            except:
                pass
                
        old_fav_key = f"{family}/{filename}"
        new_fav_key = f"{family}/{new_filename}"
        with favorites_lock:
            favs = load_favorites()
            if old_fav_key in favs:
                favs.pop(old_fav_key)
                favs[new_fav_key] = True
                save_favorites(favs)
                
        files_json_path = family_dir / "files_list.json"
        progress_json_path = family_dir / "progress.json"
        
        if files_json_path.exists():
            try:
                with open(files_json_path, "r", encoding="utf-8") as f_list:
                    files_list = json.load(f_list)
                    
                progress = {}
                if progress_json_path.exists():
                    with open(progress_json_path, "r", encoding="utf-8") as f_prog:
                        progress = json.load(f_prog)
                        
                for item in files_list:
                    title = item["title"]
                    base_name = sanitize_filename(title)
                    _, ext = os.path.splitext(title)
                    if not ext:
                        ext = ".jpg"
                    if base_name.lower().endswith(ext.lower()):
                        base_name = base_name[:-len(ext)]
                    if (base_name + ext).lower() == filename.lower():
                        _, new_ext = os.path.splitext(new_filename)
                        new_title_base = new_filename[:-len(new_ext)] if new_filename.lower().endswith(new_ext.lower()) else new_filename
                        new_title = f"File:{new_title_base}{new_ext}"
                        
                        item["title"] = new_title
                        
                        if title in progress:
                            progress[new_title] = progress.pop(title)
                        break
                        
                with open(files_json_path, "w", encoding="utf-8") as f_list:
                    json.dump(files_list, f_list, indent=2, ensure_ascii=False)
                    
                if progress_json_path.exists():
                    with open(progress_json_path, "w", encoding="utf-8") as f_prog:
                        json.dump(progress, f_prog, indent=2, ensure_ascii=False)
            except:
                pass
                
        return jsonify({"status": "renamed", "new_filename": new_filename})
    except Exception as e:
        return jsonify({"error": f"Failed to rename: {e}"}), 500

gemini_rate_lock = threading.Lock()
last_gemini_call_time = 0.0

def call_gemini_with_rate_limit(url, payload, headers, max_retries=5):
    global last_gemini_call_time
    min_interval = 4.2  # Enforces max ~14 requests per minute (strictly below 15 RPM free tier limit)
    
    with gemini_rate_lock:
        now = time.time()
        elapsed = now - last_gemini_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
            
        for attempt in range(max_retries):
            resp = requests.post(url, json=payload, headers=headers, timeout=35)
            last_gemini_call_time = time.time()
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_sec = int(retry_after) if (retry_after and retry_after.isdigit()) else (6 * (attempt + 1))
                time.sleep(sleep_sec)
                continue
            return resp
            
        return resp

@app.route("/api/ai-classify", methods=["POST"])
def ai_classify_image():
    data = request.json or {}
    family = data.get("family")
    filename = data.get("filename")
    
    if not family or not filename:
        return jsonify({"error": "Faltan parámetros"}), 400
        
    index_json_path = COLLECTION_DIR / "indice_familias.json"
    if not index_json_path.exists():
        return jsonify({"error": "Índice no encontrado"}), 404
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family_cap = family.capitalize()
    if family_cap not in families_map:
        return jsonify({"error": "Familia no encontrada"}), 404
        
    family_dir = Path(families_map[family_cap])
    
    file_path = None
    for root, dirs, files in os.walk(family_dir):
        if ".thumbnails" in root:
            continue
        if filename in files:
            file_path = Path(root) / filename
            break
            
    if not file_path or not file_path.exists():
        return jsonify({"error": "Archivo no encontrado"}), 404
        
    ai_cache_path = family_dir / "ai_metadata.json"
    ai_cache = {}
    if ai_cache_path.exists():
        try:
            with open(ai_cache_path, "r", encoding="utf-8") as f:
                ai_cache = json.load(f)
        except:
            pass
            
    if filename in ai_cache and not data.get("force"):
        return jsonify({"status": "success", "result": ai_cache[filename], "cached": True})
        
    import base64
    try:
        with open(file_path, "rb") as img_f:
            img_b64 = base64.b64encode(img_f.read()).decode("utf-8")
            
        ext = file_path.suffix.lower()
        mime_type = "image/jpeg" if ext in ('.jpg', '.jpeg') else ("image/png" if ext == '.png' else "image/jpeg")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={os.environ.get('GEMINI_API_KEY', '')}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": "Analiza esta ilustración botánica. Lee el texto/inscripción latina en la lámina si existe, e identifica la especie/género si es posible. Devuelve ÚNICAMENTE un objeto JSON válido con los campos: \"organ\" (Flor, Hoja, Fruto, Planta completa, Tallo, Raíz, Semilla), \"style\" (Ilustración histórica, Grabado, Fotografía, Dibujo), \"description\" (descripción botánica breve en español incluyendo posible género/especie identificado), \"tags\" (array de 3 a 5 palabras clave botánicas en español)."
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": img_b64
                            }
                        }
                    ]
                }
            ]
        }
        
        headers = {"Content-Type": "application/json"}
        resp = call_gemini_with_rate_limit(url, payload, headers)
            
        if resp and resp.status_code == 429:
            return jsonify({"error": "Límite de peticiones de Gemini IA alcanzado (429). Por favor espera unos segundos e intentalo de nuevo."}), 429

        resp.raise_for_status()
        resp_data = resp.json()
        
        raw_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
        clean_json_str = re.sub(r'```json\s*|\s*```', '', raw_text).strip()
        result_dict = json.loads(clean_json_str)
        
        ai_cache[filename] = result_dict
        with open(ai_cache_path, "w", encoding="utf-8") as f:
            json.dump(ai_cache, f, indent=2, ensure_ascii=False)
            
        return jsonify({"status": "success", "result": result_dict, "cached": False})
    except Exception as e:
        add_log(f"Error en categorización IA para {filename}: {e}")
        return jsonify({"error": f"Error al clasificar con IA: {str(e)}"}), 500

@app.after_request
def add_cors_headers(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response

if __name__ == "__main__":
    # Ensure static and templates folder exist
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=True, threaded=True)
