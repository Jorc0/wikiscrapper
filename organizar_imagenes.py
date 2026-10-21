import os
import re
import json
import shutil
import time
import requests
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_parent_categories(category_title, user_agent, cache_data):
    """Fetches parent categories of a given category, using memory/file cache if available."""
    if category_title in cache_data:
        return cache_data[category_title]
        
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "categories",
        "cllimit": "500",
        "titles": f"Category:{category_title}",
        "format": "json"
    }
    headers = {
        "User-Agent": user_agent
    }
    
    # Retry logic for 429 rate limiting
    max_attempts = 5
    parents = []
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                print(f"\n[!] Rate limited (429) en API de categorías. Durmiendo {retry_after}s...")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            data = resp.json()
            
            if "query" in data and "pages" in data["query"]:
                for page_id, page_data in data["query"]["pages"].items():
                    if "categories" in page_data:
                        for cat in page_data["categories"]:
                            title = cat["title"]
                            if title.startswith("Category:"):
                                title = title[9:]
                            parents.append(title)
            
            # Cache the result
            cache_data[category_title] = parents
            return parents
            
        except Exception as e:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            print(f"[!] Error al obtener categorías de '{category_title}': {e}")
            break
            
    return []

def extract_categories_from_html(html_path):
    """Parses categories from the saved local HTML file."""
    if not os.path.exists(html_path):
        return []
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        soup = BeautifulSoup(html_content, "html.parser")
        cat_div = soup.find("div", id="mw-normal-catlinks")
        categories = []
        if cat_div:
            for a in cat_div.find_all("a"):
                title = a.get("title", "")
                if a.text == "Categories" or "Special:Categories" in title:
                    continue
                categories.append(a.text)
        return categories
    except Exception as e:
        print(f"[!] Error al parsear HTML en {html_path}: {e}")
        return []

def find_family_for_category(category_name, families, user_agent, cache_data, category_to_family, visited=None, depth=0):
    """Recursively traces a category up its parents to find its botanical family."""
    if depth > 4:
        return None
        
    if visited is None:
        visited = set()
        
    # Check if category itself matches any family name
    for fam in families:
        if fam.lower() in category_name.lower():
            return fam
            
    if category_name in category_to_family:
        return category_to_family[category_name]
        
    if category_name in visited:
        return None
    visited.add(category_name)
    
    # Get parents
    parents = get_parent_categories(category_name, user_agent, cache_data)
    time.sleep(0.3)  # Polite sleep between category API checks
    
    # 1st pass: check direct parents for family names (fast path)
    for parent in parents:
        for fam in families:
            if fam.lower() in parent.lower():
                category_to_family[category_name] = fam
                return fam
                
    # 2nd pass: recursive checks
    for parent in parents:
        fam = find_family_for_category(parent, families, user_agent, cache_data, category_to_family, visited, depth + 1)
        if fam:
            category_to_family[category_name] = fam
            return fam
            
    return None

def main():
    data_dir = "data"
    output_collection_dir = "Coleccion_Botanica"
    
    # Load families index
    index_json_path = os.path.join(output_collection_dir, "indice_familias.json")
    if not os.path.exists(index_json_path):
        print(f"[!] No se encontró el índice de familias en {index_json_path}. Por favor ejecuta organizar_familias.py primero.")
        return
        
    with open(index_json_path, "r", encoding="utf-8") as f:
        families_map = json.load(f)
        
    families = set(families_map.keys())
    
    # Create "Desconocido" folder for unclassified elements
    unknown_dir = os.path.join(output_collection_dir, "Desconocido")
    os.makedirs(unknown_dir, exist_ok=True)
    
    # Load or initialize categories API caches
    cache_path = os.path.join(data_dir, "category_parents_cache.json")
    cache_data = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            print(f"[*] Se cargaron {len(cache_data)} categorías cacheadas.")
        except Exception as e:
            print(f"[!] Error al cargar caché de categorías: {e}")
            
    cat_to_family_path = os.path.join(data_dir, "category_to_family.json")
    category_to_family = {}
    if os.path.exists(cat_to_family_path):
        try:
            with open(cat_to_family_path, "r", encoding="utf-8") as f:
                category_to_family = json.load(f)
            print(f"[*] Se cargaron {len(category_to_family)} asociaciones de familias cacheadas.")
        except Exception as e:
            print(f"[!] Error al cargar asociaciones: {e}")
            
    # Load files list
    files_json_path = os.path.join(data_dir, "files.json")
    if not os.path.exists(files_json_path):
        print(f"[!] No se encontró files.json en {files_json_path}. Ejecuta el scraper primero.")
        return
        
    with open(files_json_path, "r", encoding="utf-8") as f:
        files_list = json.load(f)
        
    print(f"[*] Analizando {len(files_list)} archivos para clasificación botánica...")
    
    classified_count = 0
    unknown_count = 0
    skipped_count = 0
    
    # We will import sanitize_filename from scraper or redefine it
    from scraper import sanitize_filename
    
    start_time = time.time()
    
    try:
        for idx, item in enumerate(files_list, 1):
            title = item["title"]
            base_name = sanitize_filename(title)
            
            # Find file paths in download data
            _, ext = os.path.splitext(item["image_url"].split('?')[0])
            if not ext:
                ext = ".jpg"
            if base_name.lower().endswith(ext.lower()):
                base_name = base_name[:-len(ext)]
                
            src_image = os.path.join(data_dir, "images", base_name + ext)
            src_html = os.path.join(data_dir, "pages", base_name + ".html")
            
            # Skip if downloaded files don't exist yet
            if not os.path.exists(src_html) or not os.path.exists(src_image):
                skipped_count += 1
                continue
                
            # Extract categories from saved HTML page
            cats = extract_categories_from_html(src_html)
            
            # Find family
            family = None
            for cat in cats:
                # Exclude general categories
                if cat in ("CC-PD-Mark", "PD-old-100-expired", "PD-scan (PD-old-auto-expired)", 
                           "Media missing infobox template", "Files with no machine-readable author", 
                           "Files with no machine-readable source", "Thomé, Flora von Deutschland",
                           "Thomé, Flora von Deutschland - index", "Botanical illustrations"):
                    continue
                
                family = find_family_for_category(cat, families, DEFAULT_USER_AGENT, cache_data, category_to_family)
                if family:
                    break
            
            if family:
                dest_dir = families_map[family]
                classified_count += 1
                status = f"[OK: {family}]"
            else:
                dest_dir = unknown_dir
                unknown_count += 1
                status = "[DESCONOCIDO]"
                
            # Copy files to category folder
            shutil.copy2(src_image, os.path.join(dest_dir, base_name + ext))
            shutil.copy2(src_html, os.path.join(dest_dir, base_name + ".html"))
            
            print(f"[{idx}/{len(files_list)}] {status} {title}")
            
            # Save caches periodically (every 10 files)
            if idx % 10 == 0:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, indent=4, ensure_ascii=False)
                with open(cat_to_family_path, "w", encoding="utf-8") as f:
                    json.dump(category_to_family, f, indent=4, ensure_ascii=False)
                    
    except KeyboardInterrupt:
        print("\n[!] Clasificación interrumpida por el usuario.")
    finally:
        # Save final caches
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)
        with open(cat_to_family_path, "w", encoding="utf-8") as f:
            json.dump(category_to_family, f, indent=4, ensure_ascii=False)
            
        elapsed = time.time() - start_time
        print("\n--- Resumen de Clasificación Botánica ---")
        print(f"Tiempo transcurrido: {elapsed:.2f} segundos")
        print(f"Archivos clasificados con éxito: {classified_count}")
        print(f"Archivos en carpeta 'Desconocido': {unknown_count}")
        print(f"Archivos omitidos (no descargados aún): {skipped_count}")

if __name__ == "__main__":
    main()
