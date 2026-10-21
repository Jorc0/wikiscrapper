# Botánico

Catálogo de láminas botánicas históricas de dominio público, con una ficha por especie.

El objetivo no es descargar imágenes en masa, sino construir un catálogo **limpio y bien enlazado**: cada lámina lleva su licencia, autor, obra, año y número de lámina, y el taxón que representa se normaliza al nombre aceptado actual (guardando el nombre con el que aparece impreso).

Fuentes:

- **Wikimedia Commons**: colecciones concretas (Köhler, Curtis's Botanical Magazine, Flora Batava, Redouté, Blanco, Thomé).
- **Biodiversity Heritage Library**: escaneos completos de las mismas obras u otras.

El sitio es un proyecto [Astro](https://astro.build) que lee las fichas como content collection. Las imágenes se sirven desde Cloudflare R2, no desde el repositorio.

## Cómo funciona

`python -m catalogo <fase>`. Cada fase guarda su estado en `var/catalogo.sqlite` y se puede interrumpir y retomar.

| Fase | Qué hace |
|---|---|
| `crawl` | Recorre las categorías de Commons o los volúmenes de BHL y guarda **solo metadatos**. |
| `depicts` | Lee la propiedad P180 ("representa") de los structured data y resuelve los taxones en Wikidata. |
| `taxonomy` | Normaliza cada nombre con el [GBIF Backbone](https://www.gbif.org/developer/species): sinónimos, homónimos, variantes ortográficas. Añade familia, género y nombres comunes en español. |
| `filter` | Lista blanca de licencias (dominio público, CC0, CC BY, CC BY-SA). Descarta portadas, mapas, fotos y copias pequeñas. Marca las láminas con varias especies. Lo dudoso va a `var/revision.csv`. |
| `dedupe` | Detecta la misma lámina subida varias veces (sha1, número de lámina, enlace Commons↔BHL, hash perceptual) y se queda con la mejor copia. |
| `images` | Descarga a 1920 px (nunca los originales TIFF) y genera WebP/AVIF a 1600, 800 y 400 px, más la paleta de colores. |
| `upload` | Sube las variantes a Cloudflare R2. |
| `export` | Escribe una ficha JSON por especie en `src/content/plantas/`. |
| `all` | Todas las fases salvo `upload`. |
| `status` | Resumen por fuente y estado. |

Ejemplo de ficha: *Pyrus malus* en una lámina de Köhler de 1887 se cataloga bajo *Malus domestica* (Rosaceae), con el nombre original, el enlace a GBIF y Wikidata, la atribución y las URLs de las imágenes.

## Puesta en marcha

```sh
pip install -r requirements.txt
npm install
```

1. En `catalogo.toml`, pon en `user_agent` un contacto real (email o URL). Wikimedia limita mucho a los clientes sin identificar.
2. Crea un `.env` (no se sube al repositorio) con las claves que vayas a usar:

   ```sh
   BHL_API_KEY=...            # solo para fuentes de BHL
   R2_ACCOUNT_ID=...
   R2_BUCKET=...
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   R2_PUBLIC_URL=https://...  # dominio público del bucket
   ```

3. Genera el catálogo y el sitio:

   ```sh
   python -m catalogo all --source kohler   # o sin --source para todas las colecciones
   python -m catalogo upload
   python -m catalogo export
   npm run build
   ```

## Configuración

Todo vive en [`catalogo.toml`](catalogo.toml):

- **`[sources.*]`**: colecciones. En Commons, una `category` con su profundidad y filtros de subcategorías; en BHL, un `bhl_title`.
- **`[filters]`**: tamaño mínimo, confianza mínima de GBIF y umbral de duplicados.
- **`[images]`**: tamaños, formatos y pausa entre descargas.
- **`[overrides]`**: correcciones a mano por título de archivo, para fijar un nombre o descartar una lámina. Tras editarlas, ejecuta `taxonomy --refresh`, `filter`, `dedupe` y `export`.

## Estructura

```
catalogo/            pipeline en Python (una fase por módulo)
catalogo.toml        fuentes, filtros y correcciones
src/content.config.ts  esquema de las fichas (content collection)
src/content/plantas/ fichas generadas, una por especie
src/pages/           listado (/) y ficha de especie (/catalogo/<especie>/)
var/                 base de datos y caché local (ignorada por git)
```

## Licencias

Las láminas son de dominio público o tienen licencias libres. Cada ficha incluye la licencia, el autor y el enlace a la fuente. Las láminas CC BY-SA llevan `share_alike: true` y obligan a compartir igual.
