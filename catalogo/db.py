import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
-- Fase 1-2: archivos y sus metadatos, tal cual vienen de la API.
-- pageid es el de Commons; las páginas de BHL usan el PageID en negativo (origin='bhl').
CREATE TABLE IF NOT EXISTS files (
    pageid INTEGER PRIMARY KEY,
    origin TEXT NOT NULL DEFAULT 'commons',
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    names TEXT,
    category TEXT,
    mime TEXT, width INTEGER, height INTEGER, size INTEGER, sha1 TEXT,
    url TEXT, thumburl TEXT, descurl TEXT,
    license_code TEXT, license_short TEXT, license_url TEXT,
    artist TEXT, date_raw TEXT, object_name TEXT, description TEXT, credit TEXT,
    categories TEXT, attribution_required INTEGER,
    sdc_done INTEGER NOT NULL DEFAULT 0,
    crawled_at TEXT
);
CREATE TABLE IF NOT EXISTS crawled_categories (
    source TEXT, category TEXT, crawled_at TEXT,
    PRIMARY KEY (source, category)
);
-- Structured data: P180 ("representa") de cada archivo, en orden
CREATE TABLE IF NOT EXISTS depicts (
    pageid INTEGER, qid TEXT, ord INTEGER,
    PRIMARY KEY (pageid, qid)
);
-- Elementos de Wikidata (taxones y no taxones, para no volver a pedirlos)
CREATE TABLE IF NOT EXISTS wd_items (
    qid TEXT PRIMARY KEY,
    taxon_name TEXT, rank TEXT, gbif_id INTEGER,
    label_es TEXT, common_es TEXT,
    fetched_at TEXT
);
-- Fase 3: caché de GBIF por nombre y fichas de taxones aceptados
CREATE TABLE IF NOT EXISTS gbif_names (
    name TEXT PRIMARY KEY,
    usage_key INTEGER, species_key INTEGER,
    status TEXT, rank TEXT, match_type TEXT, confidence INTEGER,
    raw TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS taxa (
    gbif_key INTEGER PRIMARY KEY,
    name TEXT, authorship TEXT, rank TEXT, genus TEXT, family TEXT,
    wikidata TEXT, common_es TEXT,
    fetched_at TEXT
);
-- Una fila por lámina: lo que deciden las fases 3 y 4
CREATE TABLE IF NOT EXISTS plates (
    pageid INTEGER PRIMARY KEY,
    original_name TEXT, name_source TEXT, matched_name TEXT,
    taxon_key INTEGER, taxon_note TEXT, taxon_issue TEXT,
    other_names TEXT, multi_species INTEGER NOT NULL DEFAULT 0,
    plate TEXT, year INTEGER, artist TEXT,
    license TEXT, share_alike INTEGER,
    status TEXT, reasons TEXT,
    dhash TEXT, dup_of INTEGER,
    updated_at TEXT
);
-- Fase 5: variantes generadas y paleta
CREATE TABLE IF NOT EXISTS images (
    pageid INTEGER PRIMARY KEY,
    width INTEGER, height INTEGER,
    variants TEXT, palette TEXT,
    uploaded INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT
);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    _migrate(db)
    return db


def _migrate(db):
    """Añade columnas nuevas a bases creadas con versiones anteriores."""
    have = {r["name"] for r in db.execute("PRAGMA table_info(files)")}
    if "origin" not in have:
        db.execute("ALTER TABLE files ADD COLUMN origin TEXT NOT NULL DEFAULT 'commons'")
    if "names" not in have:
        db.execute("ALTER TABLE files ADD COLUMN names TEXT")
    db.commit()


def upsert_file(db, row):
    """Inserta o actualiza un archivo. Si ya existía (p. ej. en otra colección), conserva su fuente."""
    cols = ", ".join(row)
    marks = ", ".join(f":{c}" for c in row)
    updates = ", ".join(f"{c}=excluded.{c}" for c in row if c not in ("pageid", "source", "category"))
    db.execute(f"INSERT INTO files ({cols}) VALUES ({marks}) ON CONFLICT(pageid) DO UPDATE SET {updates}", row)


def media_key(pageid):
    """Nombre base estable de los ficheros de una lámina: '255369' (Commons) o 'bhl-303704'."""
    return f"bhl-{-pageid}" if pageid < 0 else str(pageid)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def loads(value, default=None):
    return json.loads(value) if value else default


def dumps(value):
    return json.dumps(value, ensure_ascii=False)
