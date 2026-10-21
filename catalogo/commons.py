"""Fases 1 y 2: recorrer las categorías de cada colección y guardar solo metadatos."""
import logging
import re

from . import wikidata
from .db import now, upsert_file

log = logging.getLogger(__name__)

API = "https://commons.wikimedia.org/w/api.php"
EXT_FIELDS = (
    "LicenseShortName|License|LicenseUrl|Artist|DateTimeOriginal|ObjectName|"
    "ImageDescription|Credit|Categories|AttributionRequired"
)
BATCH = 50  # máximo de ids por wbgetentities para usuarios normales


def walk_categories(client, source):
    """Recorre en anchura la categoría raíz hasta source.depth, filtrando subcategorías."""
    include = re.compile(source.include, re.I) if source.include else None
    exclude = re.compile(source.exclude, re.I) if source.exclude else None
    seen = {source.category}
    level = [source.category]
    for _ in range(source.depth):
        next_level = []
        for cat in level:
            for data in client.api_all(API, action="query", list="categorymembers",
                                       cmtitle=f"Category:{cat}", cmtype="subcat", cmlimit=500):
                for member in data["query"]["categorymembers"]:
                    sub = member["title"].removeprefix("Category:")
                    if sub in seen:
                        continue
                    if (include and not include.search(sub)) or (exclude and exclude.search(sub)):
                        log.debug("  subcategoría ignorada: %s", sub)
                        continue
                    seen.add(sub)
                    next_level.append(sub)
        level = next_level
    return sorted(seen)


def _ext(info, key):
    value = info.get("extmetadata", {}).get(key, {}).get("value")
    return None if value is None else str(value)


def _store_file(db, page, source_key, category):
    info = page["imageinfo"][0]
    attribution = _ext(info, "AttributionRequired")
    row = {
        "pageid": page["pageid"],
        "title": page["title"],
        "source": source_key,
        "category": category,
        "mime": info.get("mime"),
        "width": info.get("width"),
        "height": info.get("height"),
        "size": info.get("size"),
        "sha1": info.get("sha1"),
        "url": (info.get("url") or "").split("?")[0] or None,
        "thumburl": (info.get("thumburl") or "").split("?")[0] or None,
        "descurl": info.get("descriptionurl"),
        "license_code": _ext(info, "License"),
        "license_short": _ext(info, "LicenseShortName"),
        "license_url": _ext(info, "LicenseUrl"),
        "artist": _ext(info, "Artist"),
        "date_raw": _ext(info, "DateTimeOriginal"),
        "object_name": _ext(info, "ObjectName"),
        "description": _ext(info, "ImageDescription"),
        "credit": _ext(info, "Credit"),
        "categories": _ext(info, "Categories"),
        "attribution_required": None if attribution is None else int(attribution == "true"),
        "crawled_at": now(),
    }
    upsert_file(db, row)


def crawl(client, db, cfg, source, refresh=False):
    cats = walk_categories(client, source)
    log.info("[%s] %d categorías a recorrer", source.key, len(cats))
    done = {r["category"] for r in db.execute(
        "SELECT category FROM crawled_categories WHERE source=?", (source.key,))}
    for cat in cats:
        if cat in done and not refresh:
            continue
        count = 0
        for data in client.api_all(API, action="query", generator="categorymembers",
                                   gcmtitle=f"Category:{cat}", gcmtype="file", gcmlimit=BATCH,
                                   prop="imageinfo", iiprop="url|size|mime|sha1|extmetadata",
                                   iiurlwidth=cfg.download_width, iiextmetadatafilter=EXT_FIELDS,
                                   iiextmetadatalanguage="en"):
            for page in data.get("query", {}).get("pages", []):
                if page.get("imageinfo"):
                    _store_file(db, page, source.key, cat)
                    count += 1
        db.execute("INSERT OR REPLACE INTO crawled_categories VALUES (?, ?, ?)", (source.key, cat, now()))
        db.commit()
        log.info("[%s] %s: %d archivos", source.key, cat, count)


def fetch_depicts(client, db):
    """Lee P180 de los structured data de cada archivo y resuelve esos elementos en Wikidata."""
    pending = [r["pageid"] for r in db.execute("SELECT pageid FROM files WHERE sdc_done=0")]
    log.info("Structured data pendientes: %d archivos", len(pending))
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        data = client.api(API, action="wbgetentities", ids="|".join(f"M{p}" for p in batch), props="claims")
        for mid, entity in data.get("entities", {}).items():
            statements = entity.get("statements")
            if not isinstance(statements, dict):  # la API devuelve [] cuando no hay ninguno
                continue
            for ord_, st in enumerate(statements.get("P180", [])):
                value = st.get("mainsnak", {}).get("datavalue", {}).get("value")
                if isinstance(value, dict) and value.get("id"):
                    db.execute("INSERT OR IGNORE INTO depicts VALUES (?, ?, ?)", (int(mid[1:]), value["id"], ord_))
        db.executemany("UPDATE files SET sdc_done=1 WHERE pageid=?", [(p,) for p in batch])
        db.commit()
        log.info("  structured data: %d/%d", min(i + BATCH, len(pending)), len(pending))

    qids = [r["qid"] for r in db.execute(
        "SELECT DISTINCT qid FROM depicts WHERE qid NOT IN (SELECT qid FROM wd_items)")]
    wikidata.fetch_items(client, db, qids)
