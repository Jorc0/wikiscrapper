import os
import re
import json
import time
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_USER_AGENT = "BotanicalScraper/1.0 (contact: jorco.dev@example.com; educational/personal use)"

# Global rate limiter lock and last request timestamp
import threading
rate_limit_lock = threading.Lock()
last_request_time = 0.0

def rate_limited_request(url, headers, params=None, stream=False, timeout=20):
    """Sends requests with a global rate limit of at least 2.0s between calls, handles 429s and retries with exponential backoff."""
    global last_request_time
    min_interval = 2.0  # 2 seconds polite rate limit
    
    max_attempts = 5
    for attempt in range(max_attempts):
        with rate_limit_lock:
            now = time.time()
            elapsed = now - last_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            last_request_time = time.time()
            
        try:
            if stream:
                resp = requests.get(url, headers=headers, params=params, stream=True, timeout=timeout)
            else:
                resp = requests.get(url, headers=headers, params=params, timeout=timeout)
                
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    sleep_seconds = int(retry_after)
                else:
                    sleep_seconds = 10 * (2 ** attempt)
                print(f"\n[!] Límite de peticiones (429) en {url}. Durmiendo {sleep_seconds}s antes de reintentar...")
                time.sleep(sleep_seconds)
                continue
                
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_attempts - 1:
                sleep_seconds = 5 * (2 ** attempt)
                print(f"\n[!] Error ({e}). Reintentando en {sleep_seconds}s...")
                time.sleep(sleep_seconds)
                continue
            raise e
            
    raise Exception(f"Failed to fetch {url} after {max_attempts} attempts due to rate limiting/errors.")

def sanitize_filename(title):
    """Sanitizes a Wikimedia file title to be a valid Windows/Linux filename."""
    if title.lower().startswith("file:"):
        title = title[5:]
    sanitized = re.sub(r'[\\/*?:"<>|]', '_', title)
    sanitized = sanitized.replace(' ', '_')
    sanitized = re.sub(r'_{2,}', '_', sanitized)
    return sanitized.strip('_')

def map_families_to_categories(archivo_categorias):
    """Parses b:\\W\\categorias to map family names to exact Commons category titles."""
    patron_of = r"Botanical illustrations of ([A-Z][a-z]+)"
    patron_prefijo = r"([A-Z][a-z]+) \(?botanical illustrations"
    
    mapping = {}
    if not os.path.exists(archivo_categorias):
        print(f"[!] Archivo de categorías {archivo_categorias} no encontrado.")
        return mapping
        
    with open(archivo_categorias, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            # Clean category metadata parts like "(46 C, 2 F)"
            category_part = re.sub(r"\s*\(\d+\s*[^)]*\)", "", linea).strip()
            
            if not category_part or len(category_part) <= 2 or "Subcategories" in category_part:
                continue
                
            match_of = re.search(patron_of, category_part, re.IGNORECASE)
            match_pref = re.search(patron_prefijo, category_part, re.IGNORECASE)
            
            family_name = None
            if match_of:
                family_name = match_of.group(1).capitalize()
            elif match_pref:
                family_name = match_pref.group(1).capitalize()
                
            if family_name and not family_name.lower().endswith(('phyceae', 'phyta')):
                mapping[family_name] = category_part
                
    return mapping

def discover_files_recursive(category_title, user_agent, max_depth=3):
    """Recursively queries a Commons category to find all nested image files."""
    api_url = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": user_agent}
    
    visited_categories = set()
    categories_to_visit = [(category_title, 0)] # (category_name, depth)
    discovered_files = []
    
    print(f"[*] Escaneando recursivamente archivos para: '{category_title}'...")
    
    while categories_to_visit:
        cat_name, depth = categories_to_visit.pop(0)
        
        if cat_name in visited_categories or depth > max_depth:
            continue
        visited_categories.add(cat_name)
        
        print(f"    -> Explorando: Category:{cat_name} (nivel {depth})")
        
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{cat_name}",
            "cmlimit": "250",
            "format": "json"
        }
        
        has_more = True
        next_continue = {}
        
        while has_more:
            req_params = params.copy()
            req_params.update(next_continue)
            
            try:
                resp = rate_limited_request(api_url, headers=headers, params=req_params)
                data = resp.json()
            except Exception as e:
                print(f"[!] Error al listar miembros de '{cat_name}': {e}")
                break
                
            if "query" in data and "categorymembers" in data["query"]:
                for member in data["query"]["categorymembers"]:
                    ns = member["ns"]
                    title = member["title"]
                    
                    if ns == 6: # File namespace
                        discovered_files.append({
                            "pageid": member["pageid"],
                            "title": title
                        })
                    elif ns == 14: # Category namespace
                        subcat_name = title[9:] if title.startswith("Category:") else title
                        # Exclude self-references and non-botanical generic categories
                        if not any(x in subcat_name.lower() for x in ["herbarium", "specimen", "distribution", "maps"]):
                            categories_to_visit.append((subcat_name, depth + 1))
                            
            if "continue" in data:
                next_continue = data["continue"]
            else:
                has_more = False
                
    print(f"[+] Escaneo completo. Total de archivos únicos encontrados: {len(discovered_files)}")
    
    # Deduplicate list by title
    unique_files = {}
    for f in discovered_files:
        unique_files[f["title"]] = f
        
    return list(unique_files.values())

def fetch_file_details(file_titles, user_agent):
    """Batch queries the Wikimedia API to get image URL and description URL for files."""
    api_url = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": user_agent}
    
    file_details = []
    # Process titles in batches of 50 (API limit)
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
            print(f"[!] Error al obtener detalles del lote: {e}")
            
    return file_details

def download_file_and_page(item, family_dir, user_agent):
    """Downloads both the image file and its description HTML page into the family directory."""
    headers = {"User-Agent": user_agent}
    
    # Extract file extension from URL or use JPG as default
    _, ext = os.path.splitext(item["image_url"].split('?')[0])
    if not ext:
        ext = ".jpg"
        
    # Sanitize filename
    base_name = sanitize_filename(item["title"])
    if not base_name:
        return item["title"], False, "Could not sanitize title to a valid filename"
        
    # If base_name already ends with the extension, strip it
    if base_name.lower().endswith(ext.lower()):
        base_name = base_name[:-len(ext)]
        
    image_filename = base_name + ext
    image_path = os.path.join(family_dir, image_filename)
    html_path = os.path.join(family_dir, base_name + ".html")
    
    # 1. Download HTML page
    html_downloaded = False
    if os.path.exists(html_path) and os.path.getsize(html_path) > 0:
        html_downloaded = True
    else:
        try:
            resp = rate_limited_request(item["description_url"], headers=headers, timeout=20)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(resp.text)
            html_downloaded = True
        except Exception as e:
            return item["title"], False, f"Failed to download HTML: {e}"
            
    # 2. Download Image file
    image_downloaded = False
    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
        image_downloaded = True
    else:
        try:
            resp = rate_limited_request(item["image_url"], headers=headers, stream=True, timeout=30)
            with open(image_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            image_downloaded = True
        except Exception as e:
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass
            return item["title"], False, f"Failed to download image: {e}"
            
    return item["title"], True, "Success"

def main():
    parser = argparse.ArgumentParser(description="Recursive botanical illustrations scraper organized by family.")
    parser.add_argument("--family", type=str, required=True, 
                        help="Botanical family name to process (e.g., Asteraceae, Acoraceae).")
    parser.add_argument("--threads", type=int, default=3, 
                        help="Number of threads for downloads (defaults to 3 for rate-limit safety).")
    parser.add_argument("--depth", type=int, default=3, 
                        help="Recursion depth limit for category subfolders.")
    parser.add_argument("--limit-downloads", type=int, default=0, 
                        help="Limit total downloads for testing (0 for unlimited).")
    args = parser.parse_args()

    # Load families directories mapping
    index_json_path = os.path.join("Coleccion_Botanica", "indice_familias.json")
    if not os.path.exists(index_json_path):
        print(f"[!] No se encontró el índice de familias en {index_json_path}. Ejecuta organizar_familias.py primero.")
        return
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    family = args.family.capitalize()
    if family not in families_map:
        print(f"[!] La familia '{family}' no está registrada en el índice.")
        return
        
    family_dir = families_map[family]
    os.makedirs(family_dir, exist_ok=True)
    
    # Map families to Commons categories
    family_to_commons = map_families_to_categories("categorias")
    if family not in family_to_commons:
        print(f"[!] No se encontró una correspondencia de categoría Commons para la familia {family} en el archivo 'categorias'.")
        return
        
    commons_category = family_to_commons[family]
    print(f"[+] Iniciando proceso para la familia: {family}")
    print(f"[+] Categoría Commons: Category:{commons_category}")
    print(f"[+] Directorio de destino: {family_dir}")
    
    files_json_path = os.path.join(family_dir, "files_list.json")
    progress_json_path = os.path.join(family_dir, "progress.json")
    
    # 1. Discover or load files list
    if os.path.exists(files_json_path):
        print(f"[*] Cargando lista de archivos cacheada desde: {files_json_path}")
        with open(files_json_path, "r", encoding="utf-8") as f:
            files_list = json.load(f)
    else:
        # Discover files recursively
        discovered = discover_files_recursive(commons_category, DEFAULT_USER_AGENT, max_depth=args.depth)
        
        if not discovered:
            print(f"[!] No se encontraron archivos para la familia {family}.")
            return
            
        # Get details for discovered files
        print(f"[*] Obteniendo URLs y detalles de los {len(discovered)} archivos...")
        file_titles = [f["title"] for f in discovered]
        files_list = fetch_file_details(file_titles, DEFAULT_USER_AGENT)
        
        with open(files_json_path, "w", encoding="utf-8") as f:
            json.dump(files_list, f, indent=2, ensure_ascii=False)
        print(f"[+] Guardada lista de {len(files_list)} archivos en {files_json_path}")
        
    # Apply testing limit
    if args.limit_downloads > 0:
        files_to_download = files_list[:args.limit_downloads]
        print(f"[*] Aplicando límite de test: solo se descargarán los primeros {args.limit_downloads} archivos.")
    else:
        files_to_download = files_list
        
    # Load or initialize progress
    progress = {}
    if os.path.exists(progress_json_path):
        try:
            with open(progress_json_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
        except Exception as e:
            print(f"[!] Error al cargar progreso, reiniciando: {e}")
            
    # Filter pending downloads
    pending_files = []
    for item in files_to_download:
        title = item["title"]
        if progress.get(title) == "completed":
            base_name = sanitize_filename(title)
            _, ext = os.path.splitext(item["image_url"].split('?')[0])
            if not ext:
                ext = ".jpg"
            if base_name.lower().endswith(ext.lower()):
                base_name = base_name[:-len(ext)]
            image_path = os.path.join(family_dir, base_name + ext)
            html_path = os.path.join(family_dir, base_name + ".html")
            
            if os.path.exists(image_path) and os.path.exists(html_path):
                continue
        pending_files.append(item)
        
    total_to_download = len(pending_files)
    completed_count = len(files_to_download) - total_to_download
    errors_count = 0
    
    print(f"[*] Total archivos en la familia: {len(files_to_download)}")
    print(f"[*] Descargados previamente: {completed_count}")
    print(f"[*] Pendientes por descargar: {total_to_download}")
    
    if total_to_download == 0:
        print(f"[+] ¡Todos los archivos de la familia {family} ya están descargados!")
        return
        
    # 2. Download files
    print(f"[*] Iniciando descargas usando {args.threads} hilos concurrentes...")
    start_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = {executor.submit(download_file_and_page, item, family_dir, DEFAULT_USER_AGENT): item for item in pending_files}
            
            for future in as_completed(futures):
                item = futures[future]
                title, success, msg = future.result()
                
                if success:
                    completed_count += 1
                    progress[title] = "completed"
                    percent = (completed_count / len(files_to_download)) * 100
                    print(f"[{completed_count}/{len(files_to_download)}] ({percent:.1f}%) [OK] {title}")
                else:
                    errors_count += 1
                    progress[title] = f"error: {msg}"
                    print(f"[!] [ERROR] {title}: {msg}")
                    
                if (completed_count + errors_count) % 5 == 0:
                    with open(progress_json_path, "w", encoding="utf-8") as f:
                        json.dump(progress, f, indent=2, ensure_ascii=False)
                        
    except KeyboardInterrupt:
        print("\n[!] Descargas interrumpidas por el usuario. Guardando progreso...")
    finally:
        with open(progress_json_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
            
        elapsed = time.time() - start_time
        print(f"\n--- Resumen de Descarga de {family} ---")
        print(f"Tiempo transcurrido: {elapsed:.2f} segundos")
        print(f"Descargados con éxito: {completed_count}")
        print(f"Errores: {errors_count}")

if __name__ == "__main__":
    main()
