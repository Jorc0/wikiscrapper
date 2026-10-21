"""Fase 4: licencias, exclusiones, limpieza de metadatos y marcado de duplicados.

Cada lámina acaba en uno de tres estados:
  ok        -> entra en el catálogo
  review    -> parece válida pero el taxón no está claro (ver var/revision.csv)
  rejected  -> licencia no permitida, no es una lámina, demasiado pequeña...
"""
import csv
import html
import logging
import re
from collections import defaultdict

from .bhl import commons_links
from .db import dumps, loads

log = logging.getLogger(__name__)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/tiff", "image/webp", "image/gif"}
DEFAULT_PLATE = r"(?i)\b(?:pl|plate|tab|tafel|taf|t)\.?\s*(\d+[a-z]?)\b"
HIDDEN_DIV = re.compile(r'<div style="display: ?none;?">.*?</div>', re.S)
TAG = re.compile(r"<[^>]+>")
YEAR = re.compile(r"(?<!\d)(1[5-9]\d\d)(?!\d)")
LAST_PUBLIC_DOMAIN_YEAR = 1950  # años posteriores son casi siempre fechas de subida, no de la obra


def strip_html(text):
    if not text:
        return ""
    return " ".join(html.unescape(TAG.sub(" ", HIDDEN_DIV.sub("", text))).split())


def normalize_license(code, short):
    """Devuelve (etiqueta, share_alike) si la licencia está en la lista blanca; si no, None."""
    c = (code or "").lower().strip()
    if c in ("pd", "cc-pd", "cc-pd-mark", "pdm") or c.startswith("pd-"):
        return "Public domain", False
    if c == "cc0":
        return "CC0", False
    m = re.fullmatch(r"cc-by(-sa)?-(\d\.\d)(-[a-z]{2,3})?", c)
    if m:
        return f"CC BY{'-SA' if m[1] else ''} {m[2]}", bool(m[1])
    if c:
        return None
    # Sin código de licencia: probamos con el nombre corto
    s = (short or "").lower()
    if "public domain" in s:
        return "Public domain", False
    if s.startswith("cc0"):
        return "CC0", False
    m = re.fullmatch(r"cc[ -]by(-sa)?[ -](\d\.\d)", s)
    if m:
        return f"CC BY{'-SA' if m[1] else ''} {m[2]}", bool(m[1])
    return None


def parse_year(f, source):
    for text in (strip_html(f["date_raw"]), f["title"]):
        for y in YEAR.findall(text or ""):
            if int(y) <= LAST_PUBLIC_DOMAIN_YEAR:
                return int(y)
    return source.year if source else None


def clean_artist(raw, default):
    text = strip_html(raw).strip(" ;,.")
    if not text or text.lower() in ("unknown", "unknown author", "anonymous", "anonymous author"):
        return default
    return text


def plate_number(title, source):
    m = re.search((source and source.plate_regex) or DEFAULT_PLATE, title)
    return m[1] if m else None


def classify(cfg, f, p):
    source = cfg.sources.get(f["source"])
    override = cfg.overrides.get(f["title"], {})
    license_ = normalize_license(f["license_code"], f["license_short"])
    categories = (f["categories"] or "").split("|")
    title_re = re.compile(cfg.title_exclude) if cfg.title_exclude else None
    cat_re = re.compile(cfg.category_exclude) if cfg.category_exclude else None

    rejected = []
    if override.get("reject"):
        rejected.append(f"descartada a mano: {override['reject']}")
    if license_ is None:
        rejected.append(f"licencia no permitida: {f['license_short'] or f['license_code'] or 'desconocida'}")
    if f["mime"] not in ALLOWED_MIME:
        rejected.append(f"formato no es una imagen de lámina: {f['mime']}")
    if f["width"] is not None and f["width"] < cfg.min_width:  # BHL: no se sabe hasta descargar
        rejected.append(f"demasiado pequeña ({f['width']} px)")
    if title_re and title_re.search(f["title"]):
        rejected.append(f"el título parece de portada, índice, mapa o foto: «{title_re.search(f['title'])[0]}»")
    bad_cats = [c for c in categories if cat_re and cat_re.search(c)]
    if bad_cats:
        rejected.append(f"categoría excluida: {bad_cats[0]}")

    if rejected:
        status, reasons = "rejected", rejected
    elif p["taxon_issue"]:
        status, reasons = "review", [p["taxon_issue"]]
    else:
        status, reasons = "ok", []

    return {
        "plate": plate_number(f["title"], source),
        "year": parse_year(f, source),
        "artist": clean_artist(f["artist"], source.artist if source else None),
        "license": license_[0] if license_ else None,
        "share_alike": int(license_[1]) if license_ else None,
        "status": status,
        "reasons": dumps(reasons),
        "pageid": f["pageid"],
    }


def run(db, cfg):
    rows = db.execute("SELECT f.*, p.taxon_issue FROM files f JOIN plates p USING(pageid)").fetchall()
    for f in rows:
        db.execute(
            """UPDATE plates SET plate=:plate, year=:year, artist=:artist, license=:license,
                   share_alike=:share_alike, status=:status, reasons=:reasons WHERE pageid=:pageid""",
            classify(cfg, f, f),
        )
    db.commit()
    for r in db.execute("SELECT status, COUNT(*) n FROM plates GROUP BY status"):
        log.info("  %s: %d", r["status"], r["n"])
    write_report(db, cfg.var_dir / "revision.csv")


def write_report(db, path):
    rows = db.execute(
        """SELECT p.status, f.source, f.title, p.reasons, p.original_name, p.matched_name, f.descurl
           FROM plates p JOIN files f USING(pageid)
           WHERE p.status IN ('review', 'rejected') ORDER BY p.status DESC, f.source, f.title""").fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["estado", "fuente", "archivo", "motivos", "nombre_original", "nombre_buscado", "url"])
        for r in rows:
            w.writerow([r["status"], r["source"], r["title"], "; ".join(loads(r["reasons"], [])),
                        r["original_name"], r["matched_name"], r["descurl"]])
    log.info("Informe de revisión: %s (%d filas)", path, len(rows))


BHL_ASSUMED_WIDTH = 2500  # los escaneos de página de BHL suelen rondar 2500-4000 px


def _keeper_score(r, target_width):
    """La mejor copia. Si es lo bastante grande (>= 75 % de la variante 'full'), gana la de Commons:
    suele estar recortada, retocada y con structured data. Si no, la más grande (a menudo BHL).
    Después, la versión 'clean' y la más antigua."""
    title = r["title"].lower()
    width = min(r["width"] or (BHL_ASSUMED_WIDTH if r["origin"] == "bhl" else 0), target_width)
    big_enough = width >= 0.75 * target_width
    return big_enough, big_enough and r["origin"] == "commons", width // 100, "clean" in title, \
        "original" not in title, -abs(r["pageid"])


def mark_duplicates(db, cfg):
    """Agrupa láminas de la misma especie que son la misma imagen y se queda con la mejor.

    Son duplicados si coinciden en sha1, en (obra, número de lámina), si una lámina de Commons
    cita la página de BHL de la otra, o si su hash perceptual difiere en <= dup_hamming bits.
    """
    links = commons_links(db)
    work = {k: s.work for k, s in cfg.sources.items()}
    target_width = max(cfg.variants.values())

    db.execute("UPDATE plates SET dup_of=NULL")
    rows = db.execute(
        """SELECT p.pageid, p.taxon_key, p.plate, p.dhash, f.source, f.origin, f.sha1, f.width, f.height, f.title
           FROM plates p JOIN files f USING(pageid) WHERE p.status='ok'""").fetchall()
    by_taxon = defaultdict(list)
    for r in rows:
        by_taxon[r["taxon_key"]].append(r)

    total = 0
    for group in by_taxon.values():
        parent = list(range(len(group)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, a in enumerate(group):
            for j in range(i + 1, len(group)):
                b = group[j]
                same = (a["sha1"] and a["sha1"] == b["sha1"]) \
                    or (a["plate"] and a["plate"] == b["plate"]
                        and work.get(a["source"], a["source"]) == work.get(b["source"], b["source"])) \
                    or links.get(-a["pageid"]) == b["pageid"] or links.get(-b["pageid"]) == a["pageid"] \
                    or (a["dhash"] and b["dhash"]
                        and (int(a["dhash"], 16) ^ int(b["dhash"], 16)).bit_count() <= cfg.dup_hamming)
                if same:
                    parent[find(j)] = find(i)

        clusters = defaultdict(list)
        for i, r in enumerate(group):
            clusters[find(i)].append(r)
        for members in clusters.values():
            if len(members) < 2:
                continue
            keeper = max(members, key=lambda r: _keeper_score(r, target_width))
            for r in members:
                if r is not keeper:
                    db.execute("UPDATE plates SET dup_of=? WHERE pageid=?", (keeper["pageid"], r["pageid"]))
                    total += 1
    db.commit()
    log.info("Duplicados marcados: %d", total)
