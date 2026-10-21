"""Fase 6: una ficha JSON por especie aceptada, lista para una content collection de Astro."""
import json
import logging
import re
import unicodedata
from collections import defaultdict

from .db import loads
from .filters import strip_html

log = logging.getLogger(__name__)


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _images(variants_json, base):
    variants = loads(variants_json)
    if not variants:
        return None
    url = lambda key: f"{base.rstrip('/')}/{key}" if base else f"/{key}"
    out = {name: url(v["webp"]) for name, v in variants.items() if "webp" in v}
    full = variants.get("full") or max(variants.values(), key=lambda v: v["width"])
    out["width"], out["height"] = full["width"], full["height"]
    out["formats"] = [fmt for fmt in ("avif", "webp") if fmt in full]
    return out


def run(db, cfg, include_review=False):
    statuses = ("ok", "review") if include_review else ("ok",)
    rows = db.execute(
        f"""SELECT p.*, f.title, f.source, f.origin, f.descurl, f.license_url, f.attribution_required, f.credit,
                   t.name AS t_name, t.authorship, t.rank, t.genus, t.family, t.wikidata, t.common_es,
                   i.variants, i.palette
            FROM plates p JOIN files f USING(pageid)
            JOIN taxa t ON t.gbif_key = p.taxon_key
            LEFT JOIN images i USING(pageid)
            WHERE p.status IN ({','.join('?' * len(statuses))}) AND p.dup_of IS NULL
            ORDER BY t.name, p.year, f.source""", statuses).fetchall()

    alternates = defaultdict(list)
    for r in db.execute("SELECT p.dup_of, f.descurl FROM plates p JOIN files f USING(pageid) WHERE p.dup_of IS NOT NULL"):
        alternates[r["dup_of"]].append(r["descurl"])

    species = {}
    for r in rows:
        key = r["taxon_key"]
        if key not in species:
            species[key] = {
                "taxon": {
                    "accepted": r["t_name"],
                    "authorship": r["authorship"],
                    "rank": (r["rank"] or "").lower(),
                    "genus": r["genus"],
                    "family": r["family"],
                    "gbif_id": key,
                    "wikidata": r["wikidata"],
                    "common_es": loads(r["common_es"], []),
                    "original_names": [],
                },
                "illustrations": [],
            }
        sp = species[key]
        if r["original_name"] and r["original_name"] not in sp["taxon"]["original_names"]:
            sp["taxon"]["original_names"].append(r["original_name"])

        source = cfg.sources.get(r["source"])
        sp["illustrations"].append({
            "pageid": r["pageid"],
            "original_name": r["original_name"],
            "taxon_note": r["taxon_note"],
            "multi_species": bool(r["multi_species"]),
            "other_taxa": loads(r["other_names"], []),
            "artist": r["artist"],
            "work": source.work if source else r["source"],
            "source": r["source"],
            "origin": r["origin"],
            "plate": r["plate"],
            "year": r["year"],
            "license": r["license"],
            "license_url": r["license_url"],
            "share_alike": bool(r["share_alike"]),
            "attribution_required": r["attribution_required"] != 0,
            "credit": strip_html(r["credit"]) or None,
            "source_url": r["descurl"],
            "file_title": r["title"],
            "needs_review": r["status"] == "review",
            "alternates": alternates.get(r["pageid"], []),
            "palette": loads(r["palette"], []),
            "images": _images(r["variants"], cfg.image_base),
        })

    out_dir = cfg.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    written, used_slugs = set(), set()
    for key, sp in sorted(species.items(), key=lambda kv: kv[1]["taxon"]["accepted"]):
        slug = slugify(sp["taxon"]["accepted"])
        if slug in used_slugs:
            slug = f"{slug}-{key}"
        used_slugs.add(slug)

        used_ids, illustrations = set(), []
        for ill in sp["illustrations"]:
            base = f"{slug}-{slugify(ill['source'])}-{ill['year'] or 'sf'}"
            ill_id = base if base not in used_ids else f"{base}-{slugify(ill['plate'] or str(ill['pageid']))}"
            used_ids.add(ill_id)
            illustrations.append({"id": ill_id, **ill})
        sp["illustrations"] = illustrations
        sp["taxon"]["original_names"] = [n for n in sp["taxon"]["original_names"]
                                         if n.lower() != sp["taxon"]["accepted"].lower()]

        path = out_dir / f"{slug}.json"
        path.write_text(json.dumps(sp, ensure_ascii=False, indent=2), encoding="utf-8")
        written.add(path.name)

    # La carpeta es generada: se borran las fichas de especies que ya no salen
    for stale in out_dir.glob("*.json"):
        if stale.name not in written:
            stale.unlink()

    without_images = sum(1 for sp in species.values() for i in sp["illustrations"] if not i["images"])
    log.info("Exportadas %d especies (%d láminas) a %s", len(species),
             sum(len(sp["illustrations"]) for sp in species.values()), out_dir)
    if without_images:
        log.info("  %d láminas aún sin imágenes procesadas (images: null)", without_images)
    if not cfg.image_base:
        log.warning("  Sin image_base: las URLs son relativas (/laminas/...). Define R2_PUBLIC_URL o CATALOGO_IMAGE_BASE.")
