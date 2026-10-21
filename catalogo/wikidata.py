import logging
import re

from .db import dumps, now
from .net import ApiError

log = logging.getLogger(__name__)

API = "https://www.wikidata.org/w/api.php"
RANKS = {
    "Q7432": "species", "Q68947": "subspecies", "Q767728": "variety", "Q279749": "form",
    "Q34740": "genus", "Q35409": "family",
}


def _values(claims, prop):
    out = []
    for st in claims.get(prop, []):
        value = st.get("mainsnak", {}).get("datavalue", {}).get("value")
        if value is not None:
            out.append(value)
    return out


# "Rosa alba", "Rosa × alba", "Rosa eglanteria var punicea": sinónimos latinos, no nombres comunes
LATIN_NAME = re.compile(r"^[A-Z][a-z]+ (×\s?)?[a-z-]+(\s+(var|subsp|ssp|f|fo|forma|cv)\.?\s+\S+)*$")


def common_names(texts, scientific):
    """Nombres comunes sin duplicados, en minúscula inicial y sin repetir el nombre científico."""
    out, seen = [], {(scientific or "").lower().replace("× ", "×")}
    for t in texts:
        t = t.strip()
        if t and not LATIN_NAME.match(t) and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t[0].lower() + t[1:] if not t[:2].isupper() else t)
    return out


def fetch_items(client, db, qids):
    qids = sorted(set(qids))
    for i in range(0, len(qids), 50):
        batch = qids[i:i + 50]
        data = client.api(API, action="wbgetentities", ids="|".join(batch),
                          props="claims|labels|aliases", languages="es")
        for qid, entity in data.get("entities", {}).items():
            claims = entity.get("claims") or {}
            taxon_name = next(iter(_values(claims, "P225")), None)
            rank = next((RANKS.get(v["id"], v["id"]) for v in _values(claims, "P105")), None)
            gbif = next(iter(_values(claims, "P846")), None)
            label = entity.get("labels", {}).get("es", {}).get("value")
            names = [v["text"] for v in _values(claims, "P1843") if v.get("language") == "es"]
            if label:
                names.append(label)
            names += [a["value"] for a in entity.get("aliases", {}).get("es", [])]
            db.execute(
                "INSERT OR REPLACE INTO wd_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                (qid, taxon_name, rank, int(gbif) if gbif and str(gbif).isdigit() else None,
                 label, dumps(common_names(names, taxon_name)), now()),
            )
        db.commit()
        log.info("  Wikidata: %d/%d elementos", min(i + 50, len(qids)), len(qids))


def find_taxon(client, gbif_key, name):
    """Busca el elemento de Wikidata de un taxón: primero por ID de GBIF (P846) y, como los
    IDs de Wikidata a menudo van por detrás del backbone de GBIF, después por nombre (P225)."""
    for query in (f"haswbstatement:P846={gbif_key}", f'haswbstatement:"P225={name}"'):
        try:
            data = client.api(API, action="query", list="search", srsearch=query, srlimit=1)
        except ApiError as e:
            log.warning("  búsqueda en Wikidata fallida (%s): %s", query, e)
            continue
        hits = data.get("query", {}).get("search", [])
        if hits:
            return hits[0]["title"]
    return None
