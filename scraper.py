import os
import sys
import re
import json
import time
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

# Define constant User-Agent to respect Wikimedia policy
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

import threading

# A simple lock-based rate limiter to ensure we don't request too fast
rate_limit_lock = threading.Lock()
last_request_time = 0.0

def rate_limited_request(url, headers, stream=False, timeout=20):
    global last_request_time
    
    # We want at least 0.5 seconds between requests globally
    min_interval = 0.5
    
    max_attempts = 5
    for attempt in range(max_attempts):
        with rate_limit_lock:
            now = time.time()
            elapsed = now - last_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            last_request_time = time.time()
            
        try:
            resp = requests.get(url, headers=headers, stream=stream, timeout=timeout)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 30))
                print(f"\n[!] Rate limited (429) on {url}. Sleeping for {retry_after}s before retry...")
                time.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_attempts - 1:
                # Exponential backoff for network issues
                sleep_time = 2 ** attempt
                time.sleep(sleep_time)
                continue
            raise e
            
    raise Exception(f"Failed to fetch {url} after {max_attempts} attempts due to rate limiting or errors.")

def sanitize_filename(title):
    """Sanitizes a Wikimedia file title to be a valid Windows/Linux filename."""
    # Strip "File:" prefix
    if title.lower().startswith("file:"):
        title = title[5:]
    # Replace invalid filesystem characters with underscores
    sanitized = re.sub(r'[\\/*?:"<>|]', '_', title)
    # Replace multiple underscores and spaces
    sanitized = sanitized.replace(' ', '_')
    sanitized = re.sub(r'_{2,}', '_', sanitized)
    return sanitized.strip('_')

def fetch_category_files(category_title, user_agent):
    """Fetches the list of all files in the given category using the MediaWiki Action API."""
    api_url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "categorymembers",
        "gcmtitle": category_title,
        "gcmtype": "file",
        "gcmlimit": "250",  # Safe batch limit
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "format": "json"
    }
    headers = {
        "User-Agent": user_agent
    }
    
    files = []
    next_continue = {}
    has_more = True
    
    print(f"[*] Fetching media list for category: '{category_title}'...")
    
    while has_more:
        req_params = params.copy()
        req_params.update(next_continue)
        
        try:
            response = requests.get(api_url, params=req_params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"[!] Error fetching category members: {e}")
            break
        
        if "query" in data and "pages" in data["query"]:
            pages = data["query"]["pages"]
            for page_id, page_data in pages.items():
                if "imageinfo" in page_data and len(page_data["imageinfo"]) > 0:
                    image_info = page_data["imageinfo"][0]
                    desc_url = image_info.get("descriptionurl")
                    if not desc_url:
                        safe_title = page_data["title"].replace(" ", "_")
                        desc_url = f"https://commons.wikimedia.org/wiki/{safe_title}"
                        
                    files.append({
                        "pageid": page_data["pageid"],
                        "title": page_data["title"],
                        "image_url": image_info["url"],
                        "description_url": desc_url,
                        "size": image_info.get("size", 0),
                        "mime": image_info.get("mime", "")
                    })
        
        if "continue" in data:
            next_continue = data["continue"]
            print(f"[*] Fetched {len(files)} files so far...")
        else:
            has_more = False
            
    print(f"[+] Total files found in category: {len(files)}")
    return files

def download_single_item(item, output_dir, user_agent, retries=3):
    """Downloads both the image file and its description HTML page."""
    images_dir = os.path.join(output_dir, "images")
    pages_dir = os.path.join(output_dir, "pages")
    
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
    image_path = os.path.join(images_dir, image_filename)
    html_path = os.path.join(pages_dir, base_name + ".html")
    
    headers = {
        "User-Agent": user_agent
    }
    
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
            return item["title"], False, f"Failed to download description page HTML: {e}"
        
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
            # Cleanup partial file if it exists
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except:
                    pass
            return item["title"], False, f"Failed to download image file: {e}"
        
    return item["title"], True, "Success"

def main():
    parser = argparse.ArgumentParser(description="Scrapes Wikimedia category files (images + HTML pages).")
    parser.add_argument("--category", type=str, default="Category:Thomé,_Flora_von_Deutschland", 
                        help="Wikimedia Commons Category title.")
    parser.add_argument("--output-dir", type=str, default="data", 
                        help="Directory to save the scraped content.")
    parser.add_argument("--limit", type=int, default=0, 
                        help="Limit the number of files to download (0 for unlimited).")
    parser.add_argument("--threads", type=int, default=5, 
                        help="Number of concurrent download threads.")
    parser.add_argument("--user-agent", type=str, default=DEFAULT_USER_AGENT, 
                        help="Custom User-Agent header.")
    args = parser.parse_args()

    # Ensure output directories exist
    output_dir = args.output_dir
    images_dir = os.path.join(output_dir, "images")
    pages_dir = os.path.join(output_dir, "pages")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(pages_dir, exist_ok=True)
    
    files_json_path = os.path.join(output_dir, "files.json")
    progress_json_path = os.path.join(output_dir, "progress.json")
    
    # Step 1: Get or load the list of files
    if os.path.exists(files_json_path):
        print(f"[*] Loading files list from cached: {files_json_path}")
        with open(files_json_path, "r", encoding="utf-8") as f:
            files_list = json.load(f)
    else:
        files_list = fetch_category_files(args.category, args.user_agent)
        if files_list:
            with open(files_json_path, "w", encoding="utf-8") as f:
                json.dump(files_list, f, indent=2, ensure_ascii=False)
            print(f"[+] Saved files list to {files_json_path}")
        else:
            print("[!] No files found to process. Exiting.")
            sys.exit(1)
            
    # Apply limit if specified
    if args.limit > 0:
        files_to_download = files_list[:args.limit]
        print(f"[*] Applying limit: Only processing the first {args.limit} files.")
    else:
        files_to_download = files_list
        
    # Load progress to resume
    progress = {}
    if os.path.exists(progress_json_path):
        try:
            with open(progress_json_path, "r", encoding="utf-8") as f:
                progress = json.load(f)
        except Exception as e:
            print(f"[!] Error loading progress.json, starting fresh: {e}")
            
    # Filter files that are already completed
    pending_files = []
    for item in files_to_download:
        title = item["title"]
        if progress.get(title) == "completed":
            # Double check if files physically exist
            _, ext = os.path.splitext(item["image_url"].split('?')[0])
            if not ext:
                ext = ".jpg"
            base_name = sanitize_filename(title)
            if base_name.lower().endswith(ext.lower()):
                base_name = base_name[:-len(ext)]
            image_path = os.path.join(images_dir, base_name + ext)
            html_path = os.path.join(pages_dir, base_name + ".html")
            
            if os.path.exists(image_path) and os.path.exists(html_path):
                continue
        pending_files.append(item)
        
    total_to_download = len(pending_files)
    print(f"[*] Total files in scope: {len(files_to_download)}")
    print(f"[*] Files already downloaded: {len(files_to_download) - total_to_download}")
    print(f"[*] Pending files to download: {total_to_download}")
    
    if total_to_download == 0:
        print("[+] All files are already downloaded!")
        sys.exit(0)
        
    # Step 2: Download pending files using ThreadPoolExecutor
    print(f"[*] Starting downloads using {args.threads} threads...")
    completed_count = len(files_to_download) - total_to_download
    errors_count = 0
    
    start_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            # Submit download tasks
            futures = {executor.submit(download_single_item, item, output_dir, args.user_agent): item for item in pending_files}
            
            for future in as_completed(futures):
                item = futures[future]
                title, success, message = future.result()
                
                if success:
                    completed_count += 1
                    progress[title] = "completed"
                    # Print progress inline
                    percent = (completed_count / len(files_to_download)) * 100
                    print(f"[{completed_count}/{len(files_to_download)}] ({percent:.1f}%) [OK] {title}")
                else:
                    errors_count += 1
                    progress[title] = f"error: {message}"
                    print(f"[!] [ERROR] {title}: {message}")
                    
                # Save progress periodically (every 5 successful downloads)
                if (completed_count + errors_count) % 5 == 0:
                    with open(progress_json_path, "w", encoding="utf-8") as f:
                        json.dump(progress, f, indent=2, ensure_ascii=False)
                        
    except KeyboardInterrupt:
        print("\n[!] Scraper interrupted by user. Saving current progress...")
    finally:
        # Save final progress
        with open(progress_json_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
            
        elapsed = time.time() - start_time
        print("\n--- Scraping Summary ---")
        print(f"Time elapsed: {elapsed:.2f} seconds")
        print(f"Total processed: {completed_count}")
        print(f"Total errors: {errors_count}")
        print(f"Output files stored in: {os.path.abspath(output_dir)}")
        
if __name__ == "__main__":
    main()
