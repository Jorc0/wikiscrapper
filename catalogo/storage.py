"""Subida de las variantes a Cloudflare R2 (API compatible con S3).

Variables de entorno necesarias:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
  R2_PUBLIC_URL  (dominio público del bucket; se usa al exportar)
"""
import logging
import os

from .db import loads

log = logging.getLogger(__name__)

CONTENT_TYPES = {"webp": "image/webp", "avif": "image/avif"}


def upload(db, cfg):
    try:
        import boto3
    except ImportError:
        raise SystemExit("Falta boto3: pip install boto3")
    missing = [v for v in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
               if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"Faltan variables de entorno para R2: {', '.join(missing)}")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    bucket = os.environ["R2_BUCKET"]
    rows = db.execute("SELECT pageid, variants FROM images WHERE uploaded=0").fetchall()
    log.info("Subiendo %d láminas a R2 (%s)", len(rows), bucket)
    for i, r in enumerate(rows, 1):
        for entry in loads(r["variants"], {}).values():
            for fmt, ctype in CONTENT_TYPES.items():
                if fmt in entry:
                    s3.upload_file(
                        str(cfg.var_dir / "images" / entry[fmt]), bucket, entry[fmt],
                        ExtraArgs={"ContentType": ctype, "CacheControl": "public, max-age=31536000, immutable"},
                    )
        db.execute("UPDATE images SET uploaded=1 WHERE pageid=?", (r["pageid"],))
        db.commit()
        if i % 25 == 0 or i == len(rows):
            log.info("  subidas %d/%d", i, len(rows))
