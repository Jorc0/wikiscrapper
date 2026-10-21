import os
import re
import json
import time
import threading
import requests
from requests.adapters import HTTPAdapter

DEFAULT_USER_AGENT = "BotanicalScraper/1.0 (hobbyist/personal use)"

# Shared HTTP session with connection pooling
session = requests.Session()
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
session.mount("https://", adapter)
import shutil

rate_limit_lock = threading.Lock()
last_request_time = 0.0

def safe_atomic_replace(src_path, dst_path, max_retries=5):
    """Safely replaces dst_path with src_path on Windows handling open file handles."""
    for attempt in range(max_retries):
        try:
            os.replace(src_path, dst_path)
            return True
        except PermissionError:
            time.sleep(0.15 * (attempt + 1))
        except Exception:
            time.sleep(0.15 * (attempt + 1))
    try:
        shutil.copyfile(src_path, dst_path)
        try:
            os.remove(src_path)
        except:
            pass
        return True
    except Exception as e:
        print(f"Error guardando {dst_path}: {e}")
        return False

def rate_limited_request(url, headers, params=None, timeout=25):
    """Sends requests to Wikimedia API with polite rate limiting and 429 backoff handling without holding locks while sleeping."""
    global last_request_time
    min_interval = 0.85
    
    max_attempts = 8
    for attempt in range(max_attempts):
        with rate_limit_lock:
            now = time.time()
            target_time = max(now, last_request_time + min_interval)
            last_request_time = target_time
            sleep_dur = target_time - now
            
        if sleep_dur > 0:
            time.sleep(sleep_dur)
            
        try:
            resp = session.get(url, headers=headers, params=params, timeout=timeout)
            
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_seconds = int(retry_after) if (retry_after and retry_after.isdigit()) else (8 * (attempt + 1))
                time.sleep(sleep_seconds)
                continue
                
            resp.raise_for_status()
            
            # Handle MediaWiki JSON toomanyrequests error body
            data = resp.json()
            if isinstance(data, dict) and "error" in data and data["error"].get("code") == "toomanyrequests":
                sleep_seconds = 8 * (attempt + 1)
                time.sleep(sleep_seconds)
                continue
                
            return resp
        except Exception as e:
            if attempt < max_attempts - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise e
            
    raise Exception(f"Error al consultar Wikimedia ({url}) tras varios intentos.")

NON_BOTANICAL_KEYWORDS = [
    "herbarium", "herbaria", "specimen", "distribution", "maps", "location",
    "stamps", "monument", "statue", "flag", "coat of arms", "symbol", "logo",
    "redirect", "categories", "user", "template", "wikipedia"
]

VALID_MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff', '.pdf', '.webp', '.svg')

def is_valid_botanical_category(category_name):
    """Filters out non-botanical or maintenance category names."""
    cat_lower = category_name.lower()
    for kw in NON_BOTANICAL_KEYWORDS:
        if kw in cat_lower:
            return False
    return True

def is_valid_botanical_media(title):
    """Checks if a file has a valid image or PDF extension."""
    ext = os.path.splitext(title)[1].lower()
    return ext in VALID_MEDIA_EXTENSIONS

class PywikibotCategoryCrawler:
    """
    Level-by-level recursive Category crawler following Pywikibot design patterns.
    Explores subcategories, extracts images, avoids cyclic category loops,
    and stops when legitimate branches are exhausted or max_depth is reached.
    """
    def __init__(self, user_agent=DEFAULT_USER_AGENT):
        self.user_agent = user_agent
        self.api_url = "https://commons.wikimedia.org/w/api.php"
        self.headers = {"User-Agent": self.user_agent}

    def fetch_category_level(self, category_title):
        """Fetches direct files (ns=6) and direct subcategories (ns=14) for a given category."""
        clean_cat = category_title
        if clean_cat.startswith("Category:"):
            clean_cat = clean_cat[9:]
            
        files = []
        subcats = []
        skipped_subcats = []
        
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{clean_cat}",
            "cmlimit": "500",
            "format": "json"
        }
        
        has_more = True
        next_continue = {}
        
        while has_more:
            req_params = params.copy()
            req_params.update(next_continue)
            
            try:
                resp = rate_limited_request(self.api_url, headers=self.headers, params=req_params)
                data = resp.json()
            except Exception as e:
                break
                
            if "query" in data and "categorymembers" in data["query"]:
                for member in data["query"]["categorymembers"]:
                    ns = member["ns"]
                    title = member["title"]
                    
                    if ns == 6:  # File
                        files.append({
                            "pageid": member["pageid"],
                            "title": title,
                            "category": clean_cat
                        })
                    elif ns == 14:  # Subcategory
                        subcat_name = title[9:] if title.startswith("Category:") else title
                        if is_valid_botanical_category(subcat_name):
                            subcats.append(subcat_name)
                        else:
                            skipped_subcats.append(subcat_name)
                            
            if "continue" in data:
                next_continue = data["continue"]
            else:
                has_more = False
                
        return files, subcats, skipped_subcats

    def explore_hierarchy(self, root_category, max_depth=3, log_fn=None, checkpoint_path=None, cancel_event=None):
        """
        Level-by-level exploration down to max_depth with resilient incremental checkpointing.
        If interrupted, progress is saved in checkpoint_path and files_list.json.
        Resuming skips already explored categories instantly.
        """
        def log(msg):
            if log_fn:
                log_fn(msg)
            else:
                print(msg)
                
        def norm_title(t):
            if not t:
                return ""
            if t.startswith("Category:"):
                t = t[9:]
            return t.strip().lower().replace("_", " ").replace("-", " ")

        clean_root = root_category[9:] if root_category.startswith("Category:") else root_category
        
        visited_categories = set()
        all_files = []
        file_titles_seen = set()
        cached_category_data = {}  # cat_name -> [files, subcats, skipped_subcats]
        total_skipped_subcats = 0
        
        # Load existing checkpoint if available
        if checkpoint_path and os.path.exists(checkpoint_path):
            try:
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    ckpt = json.load(f)
                    ckpt_root = ckpt.get("root_category", "")
                    
                    norm_ckpt = norm_title(ckpt_root)
                    norm_curr = norm_title(clean_root)
                    
                    # Match if one is contained in the other or if checkpoint file exists in family folder
                    if not ckpt_root or norm_curr in norm_ckpt or norm_ckpt in norm_curr or True:
                        visited_categories = set(ckpt.get("visited_categories", []))
                        all_files = ckpt.get("all_files", [])
                        file_titles_seen = set(f["title"] for f in all_files)
                        cached_category_data = ckpt.get("cached_category_data", {})
                        total_skipped_subcats = ckpt.get("total_skipped_subcats", 0)
                        log(f"[REANUDANDO] Encontrado punto de control previo ({len(visited_categories)} categorías ya exploradas, {len(all_files)} archivos en memoria). Saltando elementos procesados...")
            except Exception as e:
                log(f"[ADVERTENCIA] No se pudo cargar el punto de control previo ({e}). Se iniciará escaneo desde cero.")

        def save_checkpoint():
            if not checkpoint_path:
                return
            try:
                ckpt_data = {
                    "root_category": clean_root,
                    "max_depth": max_depth,
                    "visited_categories": list(visited_categories),
                    "all_files": all_files,
                    "cached_category_data": cached_category_data,
                    "total_skipped_subcats": total_skipped_subcats,
                    "last_updated": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                temp_path = str(checkpoint_path) + ".tmp"
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(ckpt_data, f, indent=2, ensure_ascii=False)
                safe_atomic_replace(temp_path, str(checkpoint_path))
                
                # Save incremental files_list.json using atomic file replace
                files_json_path = os.path.join(os.path.dirname(checkpoint_path), "files_list.json")
                temp_files_path = files_json_path + ".tmp"
                with open(temp_files_path, "w", encoding="utf-8") as f:
                    json.dump(all_files, f, indent=2, ensure_ascii=False)
                safe_atomic_replace(temp_files_path, files_json_path)
            except Exception as e:
                print(f"Error guardando checkpoint: {e}")

        log(f"[*] Pywikibot Crawler activo para 'Category:{clean_root}' (Profundidad máx: {max_depth})...")
        
        category_nodes = {}
        current_level_queue = [(clean_root, 1, None)]
        
        for cur_depth in range(1, max_depth + 1):
            if not current_level_queue or (cancel_event and cancel_event.is_set()):
                break
                
            log(f"--- INICIANDO NIVEL {cur_depth} ({len(current_level_queue)} categorías a procesar) ---")
            next_level_queue = []
            
            for cat_name, depth_val, parent_name in current_level_queue:
                if cancel_event and cancel_event.is_set():
                    break
                    
                clean_cat = cat_name[9:] if cat_name.startswith("Category:") else cat_name
                is_already_visited = (clean_cat in visited_categories or cat_name in visited_categories)
                cached_data = cached_category_data.get(clean_cat) or cached_category_data.get(cat_name)
                
                # Only use cache if it contains non-empty valid files or subcats
                use_cache = is_already_visited and cached_data and (len(cached_data[0]) > 0 or len(cached_data[1]) > 0)
                
                if use_cache:
                    cat_files, cat_subcats, cat_skipped = cached_data
                    log(f"  [Pywikibot Level {cur_depth}] [CACHÉ] Reusando Category:{clean_cat} ({len(cat_files)} archivos)")
                else:
                    log(f"  [Pywikibot Level {cur_depth}] Explorando Category:{clean_cat}")
                    cat_files, cat_subcats, cat_skipped = self.fetch_category_level(clean_cat)
                    
                    visited_categories.add(clean_cat)
                    cached_category_data[clean_cat] = [cat_files, cat_subcats, cat_skipped]
                    total_skipped_subcats += len(cat_skipped)
                    
                    added_files = 0
                    for f in cat_files:
                        if f["title"] not in file_titles_seen:
                            file_titles_seen.add(f["title"])
                            all_files.append(f)
                            added_files += 1
                            
                    log(f"   -> Category:{clean_cat}: {len(cat_files)} archivos ({added_files} nuevos), {len(cat_subcats)} subcategorías. [Acumulado: {len(all_files)} archivos en {len(visited_categories)} categorías]")
                    
                    if cat_skipped:
                        log(f"      [FILTRADO] Omitidas {len(cat_skipped)} subcategorías no botánicas")
                        
                    save_checkpoint()
                    
                node = {
                    "name": clean_cat,
                    "depth": cur_depth,
                    "files_count": len(cat_files),
                    "children": []
                }
                category_nodes[clean_cat] = node
                
                if parent_name and parent_name in category_nodes:
                    category_nodes[parent_name]["children"].append(node)
                    
                if cur_depth < max_depth:
                    for subcat in cat_subcats:
                        sub_clean = subcat[9:] if subcat.startswith("Category:") else subcat
                        next_level_queue.append((sub_clean, cur_depth + 1, clean_cat))
                        
            current_level_queue = next_level_queue
            
        tree = category_nodes.get(clean_root)
        save_checkpoint()
        
        log("==================================================")
        log(" RESUMEN DE ESCANEO PYWIKIBOT")
        log("==================================================")
        log(f" - Categorías exploradas: {len(visited_categories)}")
        log(f" - Archivos únicos detectados: {len(all_files)}")
        log(f" - Subcategorías no botánicas omitidas: {total_skipped_subcats}")
        log(f" - Profundidad máxima alcanzada: {max_depth}")
        log("==================================================")
        log(f"[+] Escaneo Pywikibot completado exitosamente para 'Category:{clean_root}'.")
        
        return tree, all_files
