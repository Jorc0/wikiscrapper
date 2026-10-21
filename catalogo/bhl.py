"""Fuente Biodiversity Heritage Library: las láminas de una obra a partir de su TitleID.

Solo se guardan las páginas marcadas como 'Illustration'. Necesita BHL_API_KEY (en .env).
Las filas usan pageid = -PageID de BHL para no chocar con los pageid de Commons.
"""
import logging
import os
import re

from .db import dumps, now, upsert_file
from .net import ApiError

log = logging.getLogger(__name__)

API = "https://www.biodiversitylibrary.org/api3"
# Commons suele citar la página de BHL de la que sale una lámina: "BHL-303704" o ".../page/303704"
COMMONS_LINK = re.compile(r"(?:BHL-|biodiversitylibrary\.org/page/)(\d+)(?!\d)")


def _call(client, op, **params):
    key = os.environ.get("BHL_API_KEY")
    if not key:
        raise SystemExit("Falta BHL_API_KEY (en .env o en el entorno) para las fuentes de BHL.")
    params.update(op=op, apikey=key, format="json")
    data = client.get(API, params).json()
    if data.get("Status") != "ok":
        raise ApiError(f"BHL {op}: {data.get('ErrorMessage')}")
    return data["Result"]


def page_names(names):
    """Binomios a partir de los nombres que BHL detecta en la página.

    En las láminas el OCR suele separar género y epíteto ("ACHILLEA", "Millefolium"):
    se recombinan, y GBIF decide después si el nombre existe.
    """
    canon = [(n.get("NameCanonical") or "").strip() for n in names]
    out = []
    for i, c in enumerate(canon):
        if " " in c:
            out.append(c)
        elif c and i + 1 < len(canon) and canon[i + 1] and " " not in canon[i + 1]:
            out.append(f"{c.capitalize()} {canon[i + 1].lower()}")
    return list(dict.fromkeys(out))


def license_of(item):
    """(código de licencia al estilo de Commons, texto, URL)."""
    status = " ".join((item.get("CopyrightStatus") or "").split())
    url = item.get("LicenseUrl") or None
    m = re.search(r"creativecommons\.org/(?:licenses/([a-z-]+)/(\d\.\d)|publicdomain/(zero|mark))", url or "")
    if m:
        code = ("cc0" if m[3] == "zero" else "pd") if m[3] else f"cc-{m[1]}-{m[2]}"
    elif status.lower().startswith("public domain"):
        code = "pd"
    else:
        code = None
    return code, status or None, url


def plate_label(page):
    for n in page.get("PageNumbers", []):
        if n.get("Prefix") and n.get("Number"):
            return f"{n['Prefix']} {n['Number']}"
    return None


def crawl(client, db, cfg, source, refresh=False):
    title = _call(client, "GetTitleMetadata", id=source.bhl_title, items="t")[0]
    items = [i for i in title.get("Items", []) if not source.bhl_items or int(i["ItemID"]) in source.bhl_items]
    authors = ", ".join(a["Name"] for a in title.get("Authors", []) if a.get("Name")) or None
    log.info("[%s] BHL «%s»: %d volúmenes", source.key, title.get("ShortTitle") or title.get("FullTitle"), len(items))
    done = {r["category"] for r in db.execute(
        "SELECT category FROM crawled_categories WHERE source=?", (source.key,))}

    for it in items:
        tag = f"BHL item {it['ItemID']}"
        if tag in done and not refresh:
            continue
        item = _call(client, "GetItemMetadata", id=it["ItemID"], pages="t", ocr="f", parts="f")[0]
        code, status, license_url = license_of(item)
        credit = "; ".join(x for x in ("Biodiversity Heritage Library", item.get("HoldingInstitution"),
                                       item.get("Sponsor") and f"digitalizado con apoyo de {item['Sponsor']}") if x)
        plates = [p for p in item.get("Pages", [])
                  if any(t["PageTypeName"].strip() == "Illustration" for t in p.get("PageTypes", []))]
        for p in plates:
            # GetItemMetadata no trae nombres: hace falta una llamada por página
            meta = _call(client, "GetPageMetadata", pageid=p["PageID"], names="t", ocr="f")[0]
            label = plate_label(p)
            upsert_file(db, {
                "pageid": -int(p["PageID"]),
                "origin": "bhl",
                "title": f"{source.work}, {item.get('Volume') or ''} ({item.get('Year') or 's. f.'})"
                         f"{', ' + label if label else ''} [BHL {p['PageID']}]",
                "source": source.key,
                "category": tag,
                "names": dumps(page_names(meta.get("Names", []))),
                "mime": "image/webp",
                "url": p.get("FullSizeImageUrl"),
                "thumburl": p.get("ThumbnailUrl"),
                "descurl": p.get("PageUrl"),
                "license_code": code,
                "license_short": status,
                "license_url": license_url,
                "artist": source.artist or authors,
                "date_raw": item.get("Year"),
                "credit": credit,
                "sdc_done": 1,
                "crawled_at": now(),
            })
        db.execute("INSERT OR REPLACE INTO crawled_categories VALUES (?, ?, ?)", (source.key, tag, now()))
        db.commit()
        log.info("[%s] %s (%s %s): %d láminas", source.key, tag, item.get("Volume"), item.get("Year"), len(plates))


def commons_links(db):
    """{PageID de BHL: pageid de Commons} para las láminas de Commons que citan su página de BHL."""
    links = {}
    for r in db.execute("SELECT pageid, title, credit, description FROM files WHERE origin='commons'"):
        text = " ".join(x or "" for x in (r["title"], r["credit"], r["description"]))
        for page in COMMONS_LINK.findall(text):
            links.setdefault(int(page), r["pageid"])
    return links
