"""Fase 5: imágenes.

Nunca se descargan los originales (hay TIFF de 50-200 MB). Se pide a Wikimedia una miniatura
de tamaño estándar (los tamaños no estándar se redondean o se limitan) y aquí se generan las
variantes WebP/AVIF. Todo vive en var/, fuera del sitio de Astro, hasta que se sube a R2.
"""
import io
import logging
import re
from urllib.parse import quote

from PIL import Image

from .db import dumps, media_key, now

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 200_000_000
HASH_WIDTH = 250  # tamaño estándar de miniatura en Wikimedia
THUMB_SEGMENT = re.compile(r"^((?:lossy-)?(?:page\d+-)?)(\d+)px-")


def thumb_url(f, width):
    """URL de la miniatura de `width` px en upload.wikimedia.org (nunca en los servidores de la wiki)."""
    if f["pageid"] < 0:
        # BHL no sirve tamaños a medida: miniatura fija (~465 px) o la página completa
        return f["thumburl"] if width <= 465 else f["url"]
    if f["thumburl"]:
        head, _, last = f["thumburl"].rpartition("/")
        if THUMB_SEGMENT.match(last):
            return f"{head}/{THUMB_SEGMENT.sub(lambda m: f'{m[1]}{width}px-', last, count=1)}"
    url = (f["url"] or "").split("?")[0]
    # Sin miniatura en la API: el original es más estrecho que download_width
    if width >= (f["width"] or 0):
        return url
    # Ruta estándar de miniaturas: /commons/a/ab/Nombre.jpg -> /commons/thumb/a/ab/Nombre.jpg/250px-Nombre.jpg
    m = re.match(r"^(https://upload\.wikimedia\.org/wikipedia/commons)/(\w/\w\w)/([^/]+)$", url)
    if m:
        return f"{m[1]}/thumb/{m[2]}/{m[3]}/{width}px-{m[3]}"
    name = f["title"].removeprefix("File:").replace(" ", "_")
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}?width={width}"


def to_rgb(img):
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def dhash(img):
    """Hash de diferencias de 64 bits: resistente a recompresión, cambios de tamaño y retoques leves."""
    px = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = bits << 1 | (px[row * 9 + col] < px[row * 9 + col + 1])
    return f"{bits:016x}"


MAX_CONSECUTIVE_FAILURES = 5


class Throttled(RuntimeError):
    pass


class FailureGuard:
    """Corta la fase si Wikimedia rechaza varias descargas seguidas: insistir solo alarga el bloqueo."""

    def __init__(self):
        self.streak = 0

    def failed(self, title, error):
        self.streak += 1
        log.warning("  no se pudo descargar %s: %s", title, error)
        if self.streak >= MAX_CONSECUTIVE_FAILURES:
            raise Throttled(
                f"{self.streak} descargas fallidas seguidas: Wikimedia está limitando las peticiones. "
                "Vuelve a ejecutar la fase más tarde (se retoma donde se quedó); "
                "un User-Agent con contacto real y un request_interval mayor ayudan.")

    def ok(self):
        self.streak = 0


def compute_hashes(client, db):
    """Hash perceptual solo de las especies que aún tienen varias láminas sin deduplicar."""
    rows = db.execute(
        """SELECT f.* FROM files f JOIN plates p USING(pageid)
           WHERE p.status='ok' AND p.dup_of IS NULL AND p.dhash IS NULL AND p.taxon_key IN (
               SELECT taxon_key FROM plates WHERE status='ok' AND dup_of IS NULL
               GROUP BY taxon_key HAVING COUNT(*) > 1)""").fetchall()
    log.info("Calculando hash perceptual de %d láminas (miniaturas de %d px)", len(rows), HASH_WIDTH)
    guard = FailureGuard()
    try:
        for i, f in enumerate(rows, 1):
            try:
                data = client.get(thumb_url(f, HASH_WIDTH), timeout=60).content
                h = dhash(Image.open(io.BytesIO(data)))
            except Exception as e:
                guard.failed(f["title"], e)
                continue
            guard.ok()
            db.execute("UPDATE plates SET dhash=? WHERE pageid=?", (h, f["pageid"]))
            if i % 25 == 0 or i == len(rows):
                db.commit()
                log.info("  hashes: %d/%d", i, len(rows))
    except Throttled as e:
        log.warning(str(e))
    db.commit()


def palette(img, n=5):
    """Colores dominantes de la lámina, ignorando el color del papel (la mediana del borde)."""
    small = img.copy()
    small.thumbnail((200, 200))
    w, h = small.size
    border = [small.getpixel((x, y)) for x in range(w) for y in (0, h - 1)] + \
             [small.getpixel((x, y)) for y in range(h) for x in (0, w - 1)]
    paper = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))

    q = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    total = w * h
    out = []
    for count, idx in sorted(q.getcolors(), reverse=True):
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        if _dist(rgb, paper) < 45 or any(_dist(rgb, c["rgb"]) < 30 for c in out):
            continue
        out.append({"rgb": rgb, "share": round(count / total, 3)})
        if len(out) == n:
            break
    return [{"hex": "#%02x%02x%02x" % c["rgb"], "share": c["share"]} for c in out]


def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _save(img, path, fmt, quality):
    if fmt == "webp":
        img.save(path, "WEBP", quality=quality, method=6)
    elif fmt == "avif":
        img.save(path, "AVIF", quality=quality - 20)  # AVIF rinde igual con menos calidad nominal
    else:
        raise ValueError(f"Formato no soportado: {fmt}")


def process(client, db, cfg, sources=None, limit=None, refresh=False):
    raw_dir = cfg.var_dir / "cache" / f"{cfg.download_width}px"
    out_dir = cfg.var_dir / "images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "laminas").mkdir(parents=True, exist_ok=True)

    sql = """SELECT f.* FROM files f JOIN plates p USING(pageid)
             WHERE p.status='ok' AND p.dup_of IS NULL"""
    params = []
    if sources:
        sql += f" AND f.source IN ({','.join('?' * len(sources))})"
        params += sources
    if not refresh:
        sql += " AND f.pageid NOT IN (SELECT pageid FROM images)"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = db.execute(sql, params).fetchall()
    log.info("Procesando imágenes de %d láminas", len(rows))

    guard = FailureGuard()
    for i, f in enumerate(rows, 1):
        raw = raw_dir / f"{media_key(f['pageid'])}.img"
        try:
            if not raw.exists():
                client.download(thumb_url(f, cfg.download_width), raw)
            img = to_rgb(Image.open(raw))
        except Exception as e:
            try:
                guard.failed(f["title"], e)
            except Throttled as t:
                log.warning(str(t))
                return
            continue
        guard.ok()

        variants = {}
        for name, width in sorted(cfg.variants.items(), key=lambda kv: -kv[1]):
            v = img if img.width <= width else img.resize(
                (width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
            entry = {"width": v.width, "height": v.height}
            for fmt in cfg.formats:
                key = f"laminas/{media_key(f['pageid'])}-{width}w.{fmt}"
                _save(v, out_dir / key, fmt, cfg.quality)
                entry[fmt] = key
            variants[name] = entry

        db.execute(
            "INSERT OR REPLACE INTO images VALUES (?, ?, ?, ?, ?, 0, ?)",
            (f["pageid"], img.width, img.height, dumps(variants), dumps(palette(img)), now()),
        )
        db.execute("UPDATE plates SET dhash=COALESCE(dhash, ?) WHERE pageid=?", (dhash(img), f["pageid"]))
        if f["width"] is None:  # BHL: el tamaño real solo se conoce al descargar
            db.execute("UPDATE files SET width=?, height=? WHERE pageid=?", (img.width, img.height, f["pageid"]))
        db.commit()
        log.info("  [%d/%d] %s", i, len(rows), f["title"])
