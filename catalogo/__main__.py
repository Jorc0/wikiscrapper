"""Uso: python -m catalogo <fase> [opciones]

Fases, en orden:
  crawl     1. recorre cada colección (categorías de Commons o volúmenes de BHL) y guarda metadatos
  depicts   2. lee P180 de los structured data y los taxones de Wikidata
  taxonomy  3. normaliza los nombres con el GBIF Backbone
  filter    4. licencias, exclusiones, láminas múltiples -> var/revision.csv
  dedupe    4. hash perceptual (miniaturas de 250 px) y marcado de duplicados
  images    5. descarga a 1920 px y genera variantes WebP/AVIF + paleta
  upload    5. sube las variantes a Cloudflare R2 y vuelve a exportar con sus URLs
  export    6. escribe una ficha JSON por especie en src/content/plantas
  all       todo lo anterior salvo upload
  status    resumen del estado de la base de datos
"""
import argparse
import logging
import sys

from . import bhl, commons, config, export, filters, images, storage, taxonomy
from .db import connect
from .net import Client

log = logging.getLogger("catalogo")


def status(db):
    print("Archivos por fuente:")
    for r in db.execute("SELECT source, COUNT(*) n, SUM(sdc_done) sdc FROM files GROUP BY source"):
        print(f"  {r['source']:<20} {r['n']:>6}  (structured data leídos: {r['sdc']})")
    print("Láminas por estado:")
    for r in db.execute(
            "SELECT f.source, p.status, COUNT(*) n, SUM(p.dup_of IS NOT NULL) dups "
            "FROM plates p JOIN files f USING(pageid) GROUP BY f.source, p.status ORDER BY f.source, p.status"):
        print(f"  {r['source']:<20} {r['status'] or 'sin filtrar':<10} {r['n']:>6}  duplicadas: {r['dups']}")
    n_taxa = db.execute("SELECT COUNT(DISTINCT taxon_key) FROM plates WHERE status='ok' AND dup_of IS NULL").fetchone()[0]
    n_img = db.execute("SELECT COUNT(*), SUM(uploaded) FROM images").fetchone()
    print(f"Especies en el catálogo: {n_taxa}")
    print(f"Imágenes procesadas: {n_img[0]} (subidas a R2: {n_img[1] or 0})")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m catalogo", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["crawl", "depicts", "taxonomy", "filter", "dedupe",
                                          "images", "upload", "export", "all", "status"])
    parser.add_argument("--source", action="append", help="limita a una colección de catalogo.toml (repetible)")
    parser.add_argument("--limit", type=int, help="máximo de imágenes a procesar (para pruebas)")
    parser.add_argument("--refresh", action="store_true", help="rehace el trabajo ya hecho de la fase")
    parser.add_argument("--include-review", action="store_true", help="exporta también láminas pendientes de revisión")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    if args.verbose:
        logging.getLogger("PIL").setLevel(logging.INFO)

    cfg = config.load()
    unknown = set(args.source or []) - set(cfg.sources)
    if unknown:
        parser.error(f"fuentes desconocidas: {', '.join(sorted(unknown))}. Disponibles: {', '.join(cfg.sources)}")
    db = connect(cfg.db_path)
    client = Client(cfg.user_agent)
    # Descargas de upload.wikimedia.org: más despacio y con menos reintentos por archivo
    media = Client(cfg.user_agent, min_interval=cfg.request_interval, max_attempts=3)
    stages = ["crawl", "depicts", "taxonomy", "filter", "dedupe", "images", "export"] if args.stage == "all" else [args.stage]

    try:
        for stage in stages:
            log.info("== %s ==", stage)
            if stage == "crawl":
                for key in args.source or cfg.sources:
                    source = cfg.sources[key]
                    crawler = bhl.crawl if source.origin == "bhl" else commons.crawl
                    crawler(client, db, cfg, source, refresh=args.refresh)
            elif stage == "depicts":
                commons.fetch_depicts(client, db)
            elif stage == "taxonomy":
                taxonomy.run(client, db, cfg, args.source, refresh=args.refresh)
            elif stage == "filter":
                filters.run(db, cfg)
            elif stage == "dedupe":
                filters.mark_duplicates(db, cfg)  # sha1 y número de lámina, sin descargar nada
                images.compute_hashes(media, db)
                filters.mark_duplicates(db, cfg)
            elif stage == "images":
                images.process(media, db, cfg, args.source, limit=args.limit, refresh=args.refresh)
            elif stage == "upload":
                storage.upload(db, cfg)
                export.run(db, cfg, include_review=args.include_review)  # las fichas ya apuntan a R2
            elif stage == "export":
                export.run(db, cfg, include_review=args.include_review)
            elif stage == "status":
                status(db)
    except KeyboardInterrupt:
        db.commit()
        log.info("Interrumpido. El progreso guardado se retoma al volver a ejecutar la fase.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
