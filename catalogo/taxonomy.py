"""Fase 3: decidir qué taxón representa cada lámina y normalizarlo con el GBIF Backbone.

Orden de preferencia del nombre a normalizar:
  1. corrección manual en catalogo.toml ([overrides])
  2. structured data P180 que apunte a una especie de Wikidata (P225)
  3. binomios que aparezcan en el título del archivo
  4. P180 que solo apunte a un género (casi nunca basta, pero da el motivo de revisión)
El nombre original de la lámina (p. ej. "Pyrus malus") se guarda aparte.
"""
import logging
import re

from . import bhl, wikidata
from .db import dumps, loads, now

log = logging.getLogger(__name__)

GBIF = "https://api.gbif.org/v1"
SPECIES_RANKS = {"SPECIES", "SUBSPECIES", "VARIETY", "SUBVARIETY", "FORM", "SUBFORM"}

BINOMIAL = re.compile(
    r"(?<![\w-])([A-Z][a-zë]{2,})\s+(×\s*)?([a-z][a-z-]{2,})(?![a-z])"
    r"(?:\s+(var|subsp|ssp|f)\.\s*([a-z][a-z-]{2,})(?![a-z]))?"
)
# "Catasetum macrocarpum (as C. tridentatum)": el nombre impreso en la lámina es el de "as"
AS_NAME = re.compile(r"\(as\s+([A-Z][a-z]*\.?)\s+([a-z][a-z-]{2,})")
GENUS_STOP = {
    "Illustration", "Flora", "Title", "The", "Les", "Plate", "Tafel", "Volume", "Index", "Page",
    "Botanical", "Curtis", "Blanco", "Museum", "Figure", "Fig", "Table", "Abbildung",
    "Redoute", "Redouté",
}
EPITHET_STOP = {
    "von", "und", "and", "des", "der", "die", "den", "the", "from", "after", "with", "del", "dei",
    "de", "la", "les", "in", "et", "by", "for", "con", "para", "page", "volume", "vol", "plate",
    "tafel", "clean", "original", "modified", "cropped", "edition", "copy",
    "mit", "zu", "zur", "zum", "aus", "vom", "im", "am", "kurz", "nach", "oder", "sur", "par", "avec",
}


def strip_work(title, phrases):
    """Quita del título el nombre de la obra y de la categoría ("…in naturgetreuen Abbildungen mit…")."""
    for phrase in sorted({p for p in phrases if p}, key=len, reverse=True):
        for variant in (phrase, re.sub(r"\s*\([^)]*\)$", "", phrase)):
            title = re.sub(re.escape(variant), " ", title, flags=re.I)
    return title


def clean_title(title):
    title = title.removeprefix("File:").replace("_", " ")
    return re.sub(r"\.[A-Za-z0-9]{2,4}$", "", title)


def title_names(title, genera=()):
    """Binomios del título, en orden de aparición y sin repetir.

    `genera` son géneros conocidos por P180: con ellos se aceptan también epítetos
    escritos con mayúscula, como hacía Redouté ("Rosa Centifolia").
    """
    text = AS_NAME.sub("", title)
    found = []
    for genus in genera:
        for m in re.finditer(rf"(?<![\w-]){re.escape(genus)}\s+(×\s*)?([A-Za-z][a-z-]{{2,}})(?![a-z])", text):
            if m[2].lower() not in EPITHET_STOP:
                found.append((m.start(), m.end(), f"{genus} {'× ' if m[1] else ''}{m[2].lower()}"))
    for m in BINOMIAL.finditer(text):
        genus, hybrid, epithet, infra_rank, infra = m.groups()
        if genus in GENUS_STOP or epithet in EPITHET_STOP:
            continue
        name = f"{genus} {'× ' if hybrid else ''}{epithet}"
        if infra:
            name += f" {infra_rank}. {infra}"
        found.append((m.start(), m.end(), name))

    names, last_end = [], None
    for start, end, name in sorted(found):
        if last_end is not None and start < last_end:
            continue  # solapa con un nombre ya aceptado
        # Pegado al nombre anterior sin separador: es continuación ("Rosa Centifolia Anglica rubra")
        if last_end is not None and not text[last_end:start].strip():
            last_end = end
            continue
        last_end = end
        if name not in names:
            names.append(name)
    return names


def as_name(title, genus_hint):
    m = AS_NAME.search(title)
    if not m:
        return None
    genus, epithet = m.groups()
    # Expande abreviaturas del tipo "C. tridentatum" con el género del nombre principal
    if genus.endswith(".") and genus_hint and genus_hint.startswith(genus[:-1]):
        genus = genus_hint
    return f"{genus} {epithet}"


def _binomial_key(name):
    return " ".join(name.lower().replace("× ", "×").split()[:2])


def _distinct(names):
    out, seen = [], set()
    for n in names:
        if _binomial_key(n) not in seen:
            seen.add(_binomial_key(n))
            out.append(n)
    return out


def gbif_match(client, db, name):
    row = db.execute("SELECT * FROM gbif_names WHERE name=?", (name,)).fetchone()
    if row:
        return row
    # verbose=true trae las alternativas, necesarias para resolver homónimos
    r = client.get(f"{GBIF}/species/match", {"name": name, "kingdom": "Plantae", "verbose": "true"}).json()
    if r.get("kingdom") not in (None, "Plantae"):
        r["matchType"] = "NONE"
    db.execute(
        "INSERT OR REPLACE INTO gbif_names VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, r.get("usageKey"), r.get("speciesKey"), r.get("status"), r.get("rank"),
         r.get("matchType"), r.get("confidence"), dumps(r), now()),
    )
    return db.execute("SELECT * FROM gbif_names WHERE name=?", (name,)).fetchone()


def _resolve_homonyms(m):
    """GBIF da HIGHERRANK cuando el nombre existe con varios autores. Intentamos desempatar."""
    alternatives = loads(m["raw"], {}).get("alternatives", [])
    exact = [a for a in alternatives
             if (a.get("canonicalName") or "").lower() == m["name"].lower()
             and a.get("matchType") == "EXACT" and a.get("status") in ("ACCEPTED", "SYNONYM")
             and a.get("rank") in SPECIES_RANKS and a.get("speciesKey")]
    if not exact:
        return None, None, f"GBIF solo lo reconoce a nivel de {(m['rank'] or '?').lower()}"
    if len({a["speciesKey"] for a in exact}) == 1:
        return exact[0]["speciesKey"], None, None
    linnaean = [a for a in exact if a["scientificName"].endswith(" L.")]
    if len(linnaean) == 1:
        a = linnaean[0]
        return a["speciesKey"], f"nombre ambiguo; se eligió {a['scientificName']} (Linneo) → {a.get('species')}", None
    options = "; ".join(f"{a['scientificName']} → {a.get('species')}" for a in exact[:5])
    return None, None, f"nombre ambiguo con varios autores: {options}"


def evaluate(m, min_confidence):
    """(species_key, nota, problema). species_key es None si la coincidencia no es fiable."""
    if m["match_type"] == "HIGHERRANK":
        return _resolve_homonyms(m)
    if m["match_type"] in (None, "NONE") or not m["usage_key"]:
        return None, None, "GBIF no reconoce el nombre"
    if m["rank"] not in SPECIES_RANKS or not m["species_key"]:
        return None, None, f"solo indica el {(m['rank'] or '?').lower()}"
    if m["match_type"] == "FUZZY" and (m["confidence"] or 0) < min_confidence:
        return None, None, f"coincidencia aproximada dudosa ({m['confidence']}%)"
    if m["status"] == "DOUBTFUL":
        return None, None, "GBIF marca el nombre como dudoso"
    return m["species_key"], None, None


def ensure_taxon(client, db, key, hint_qids):
    """Crea la ficha del taxón aceptado (nombre, familia, género, Wikidata, nombres en español)."""
    if db.execute("SELECT 1 FROM taxa WHERE gbif_key=?", (key,)).fetchone():
        return key
    sp = client.get(f"{GBIF}/species/{key}").json()
    if sp.get("taxonomicStatus") not in (None, "ACCEPTED") and sp.get("acceptedKey"):
        return ensure_taxon(client, db, sp["acceptedKey"], hint_qids)

    name = sp.get("canonicalName") or sp.get("scientificName")
    qid = None
    if hint_qids:
        marks = ",".join("?" * len(hint_qids))
        row = db.execute(f"SELECT qid FROM wd_items WHERE (gbif_id=? OR taxon_name=?) AND qid IN ({marks})",
                         (key, name, *hint_qids)).fetchone()
        qid = row["qid"] if row else None
    if not qid:
        qid = wikidata.find_taxon(client, key, name)
    common = None
    if qid:
        if not db.execute("SELECT 1 FROM wd_items WHERE qid=?", (qid,)).fetchone():
            wikidata.fetch_items(client, db, [qid])
        common = db.execute("SELECT common_es FROM wd_items WHERE qid=?", (qid,)).fetchone()["common_es"]

    db.execute(
        "INSERT OR REPLACE INTO taxa VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, name, sp.get("authorship") or None,
         sp.get("rank"), sp.get("genus"), sp.get("family"), qid, common, now()),
    )
    return key


def resolve(client, db, cfg, f, bhl_links):
    source = cfg.sources.get(f["source"])
    title = strip_work(clean_title(f["title"]), [f["category"], source and source.work, source and source.category])
    override = cfg.overrides.get(f["title"], {})
    depicted = db.execute(
        "SELECT w.qid, w.taxon_name FROM depicts d JOIN wd_items w ON w.qid=d.qid "
        "WHERE d.pageid=? AND w.taxon_name IS NOT NULL ORDER BY d.ord", (f["pageid"],)).fetchall()
    p180 = _distinct([r["taxon_name"] for r in depicted])
    p180_species = [n for n in p180 if " " in n]
    p180_genera = [n for n in p180 if " " not in n]

    linked = []
    if f["origin"] == "bhl":
        # Nombres detectados por BHL en la página; y si una lámina de Commons cita esta página,
        # su taxón (ya revisado por P180/título) va primero
        in_title = _distinct(loads(f["names"], []))
        commons_id = bhl_links.get(-f["pageid"])
        row = commons_id and db.execute(
            "SELECT matched_name FROM plates WHERE pageid=? AND taxon_key IS NOT NULL", (commons_id,)).fetchone()
        linked = [row["matched_name"]] if row else []
    else:
        in_title = _distinct(title_names(title, {n.split(" ")[0] for n in p180}))

    if override.get("name"):
        candidates = [(override["name"], "override")]
    else:
        candidates = [(n, "commons") for n in linked] + [(n, "p180") for n in p180_species[:1]] \
            + [(n, f["origin"] == "bhl" and "bhl" or "title") for n in in_title[:3]] \
            + [(n, "p180") for n in p180_genera[:1]]

    genus_hint = (in_title or p180 or [""])[0].split(" ")[0]
    original = override.get("name") or as_name(title, genus_hint) or next(iter(in_title + p180 + linked), None)
    # Los nombres del OCR de BHL no son fiables para decidir si hay varias especies
    others = p180_species[1:] if len(p180_species) > 1 else ([] if f["origin"] == "bhl" else in_title[1:])

    taxon_key = matched = name_source = note = None
    issues = []
    for name, src in candidates:
        species_key, note, problem = evaluate(gbif_match(client, db, name), cfg.min_confidence)
        if species_key:
            taxon_key = ensure_taxon(client, db, species_key, [r["qid"] for r in depicted])
            matched, name_source = name, src
            break
        issues.append(f"«{name}»: {problem}")
    if not candidates:
        issues.append("no se encontró ningún nombre científico (ni P180 ni en el título)")

    db.execute(
        """INSERT INTO plates (pageid, original_name, name_source, matched_name, taxon_key, taxon_note,
                               taxon_issue, other_names, multi_species, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pageid) DO UPDATE SET original_name=excluded.original_name,
               name_source=excluded.name_source, matched_name=excluded.matched_name,
               taxon_key=excluded.taxon_key, taxon_note=excluded.taxon_note,
               taxon_issue=excluded.taxon_issue, other_names=excluded.other_names,
               multi_species=excluded.multi_species, updated_at=excluded.updated_at""",
        (f["pageid"], original, name_source, matched, taxon_key, note,
         None if taxon_key else " | ".join(issues), dumps(others), int(bool(others)), now()),
    )


def run(client, db, cfg, sources=None, refresh=False):
    sql = "SELECT * FROM files WHERE 1=1"
    params = []
    if sources:
        sql += f" AND source IN ({','.join('?' * len(sources))})"
        params += sources
    if not refresh:
        sql += " AND pageid NOT IN (SELECT pageid FROM plates)"
    sql += " ORDER BY origin='bhl'"  # Commons primero: BHL puede heredar sus taxones
    files = db.execute(sql, params).fetchall()
    links = bhl.commons_links(db)
    log.info("Normalizando taxonomía de %d archivos", len(files))
    for i, f in enumerate(files, 1):
        resolve(client, db, cfg, f, links)
        if i % 50 == 0 or i == len(files):
            db.commit()
            log.info("  taxonomía: %d/%d", i, len(files))
