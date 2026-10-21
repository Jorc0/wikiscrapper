import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "catalogo.toml"


@dataclass
class Source:
    key: str
    work: str
    category: str | None = None     # Commons: categoría raíz
    bhl_title: int | None = None    # BHL: TitleID de la obra (en lugar de category)
    bhl_items: list[int] | None = None  # BHL: solo estos volúmenes (ItemID); por defecto todos
    depth: int = 0
    include: str | None = None      # regex: solo se siguen subcategorías que coincidan
    exclude: str | None = None      # regex: subcategorías que se ignoran
    plate_regex: str | None = None  # regex con un grupo: número de lámina en el título
    year: int | None = None         # año por defecto si los metadatos no lo dan
    artist: str | None = None       # autor por defecto si los metadatos no lo dan

    @property
    def origin(self):
        return "bhl" if self.bhl_title else "commons"


@dataclass
class Config:
    user_agent: str
    sources: dict[str, Source]
    var_dir: Path
    export_dir: Path
    image_base: str
    min_width: int
    min_confidence: int
    dup_hamming: int
    title_exclude: str
    category_exclude: str
    download_width: int
    request_interval: float
    variants: dict[str, int]
    formats: list[str]
    quality: int
    overrides: dict[str, dict]

    @property
    def db_path(self):
        return self.var_dir / "catalogo.sqlite"


def load_dotenv(path=ROOT / ".env"):
    """Carga claves locales (p. ej. BHL_API_KEY) sin pisar variables ya definidas."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"'))


def load(path=CONFIG_PATH):
    load_dotenv()
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    general = raw.get("general", {})
    filters = raw.get("filters", {})
    images = raw.get("images", {})
    export = raw.get("export", {})

    user_agent = os.environ.get("CATALOGO_USER_AGENT") or general.get("user_agent", "")
    if not user_agent or "example.org" in user_agent:
        raise SystemExit(
            "Configura un User-Agent con un contacto real en catalogo.toml ([general] user_agent) "
            "o en la variable CATALOGO_USER_AGENT. Wikimedia bloquea los User-Agent genéricos."
        )

    sources = {k: Source(key=k, **v) for k, v in raw.get("sources", {}).items()}
    for s in sources.values():
        if bool(s.category) == bool(s.bhl_title):
            raise SystemExit(f"La fuente '{s.key}' necesita `category` (Commons) o `bhl_title` (BHL), no ambos.")

    return Config(
        user_agent=user_agent,
        sources=sources,
        var_dir=ROOT / general.get("var_dir", "var"),
        export_dir=ROOT / export.get("dir", "src/content/plantas"),
        image_base=os.environ.get("CATALOGO_IMAGE_BASE") or os.environ.get("R2_PUBLIC_URL") or export.get("image_base", ""),
        min_width=filters.get("min_width", 800),
        min_confidence=filters.get("min_confidence", 90),
        dup_hamming=filters.get("dup_hamming", 8),
        title_exclude=filters.get("title_exclude", ""),
        category_exclude=filters.get("category_exclude", ""),
        download_width=images.get("download_width", 1920),
        request_interval=images.get("request_interval", 2.0),
        variants=images.get("variants", {"full": 1600, "medium": 800, "thumb": 400}),
        formats=images.get("formats", ["webp"]),
        quality=images.get("quality", 82),
        overrides=raw.get("overrides", {}),
    )
