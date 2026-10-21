# Botánico

Catálogo de láminas botánicas históricas de dominio público o con licencias libres, con una ficha por especie.

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
| `export` | Escribe una ficha JSON por especie en `src/content/plantas/`. |
| `upload` | Sube las variantes a Cloudflare R2 y vuelve a exportar, para que las fichas apunten a las imágenes publicadas. |
| `all` | Todas las fases salvo `upload`. |
| `status` | Resumen por fuente y estado. |

Ejemplo de ficha: *Pyrus malus* en una lámina de Köhler de 1887 se cataloga bajo *Malus domestica* (Rosaceae), con el nombre original, el enlace a GBIF y Wikidata, la atribución y las URLs de las imágenes.

## Puesta en marcha

```sh
pip install -r requirements.txt
npm install
```

1. Crea un `.env` (no se sube al repositorio) con tu contacto y las claves que vayas a usar:

   ```sh
   # Wikimedia limita mucho a los clientes sin un contacto real (email o URL)
   CATALOGO_USER_AGENT=BotanicoCatalog/0.1 (contacto: tu@email.es)

   BHL_API_KEY=...            # solo para fuentes de BHL
   R2_ACCOUNT_ID=...
   R2_BUCKET=...
   R2_ACCESS_KEY_ID=...
   R2_SECRET_ACCESS_KEY=...
   # Dominio público del bucket (R2 > Settings > Public access), no el endpoint de la API S3
   R2_PUBLIC_URL=https://img.tudominio.es
   ```

2. Genera el catálogo, publica las imágenes y construye el sitio:

   ```sh
   python -m catalogo all --source kohler   # o sin --source para todas las colecciones
   python -m catalogo upload                # sube a R2 y regenera las fichas con sus URLs
   npm run build
   ```

   `all` ya exporta las fichas, pero sin imágenes publicadas (`images` apunta a rutas locales o es `null`); `upload` las completa.

## Despliegue

La web es estática y las fichas generadas están en el repositorio, así que el despliegue **no necesita Python**: solo Astro.

Con [Cloudflare Pages](https://developers.cloudflare.com/pages/), el mismo proveedor que R2:

| Ajuste | Valor |
|---|---|
| Comando de build | `npm run build` |
| Directorio de salida | `dist` |
| Variable de entorno | `NODE_VERSION=22.12.0` (Astro 7 necesita Node ≥ 22.12) |

Cada `git push` a `main` publica una versión nueva. El ciclo para actualizar el catálogo es: ejecutar el pipeline en local → `upload` → commit de `src/content/plantas/` → push.

Si usas un dominio propio para R2 (`img.tudominio.es`) y otro para la web, ambos se gestionan desde el mismo panel de Cloudflare.

## Configuración

Todo vive en [`catalogo.toml`](catalogo.toml):

- **`[sources.*]`**: colecciones. En Commons, una `category` con su profundidad y filtros de subcategorías; en BHL, un `bhl_title`.
- **`[filters]`**: tamaño mínimo, confianza mínima de GBIF y umbral de duplicados.
- **`[images]`**: tamaños, formatos y pausa entre descargas.
- **`[overrides]`**: correcciones a mano por título de archivo, para fijar un nombre o descartar una lámina. Tras editarlas, ejecuta `taxonomy --refresh`, `filter`, `dedupe` y `export`.

## Estructura

```
catalogo/              pipeline en Python (una fase por módulo)
catalogo.toml          fuentes, filtros y correcciones
src/content.config.ts  esquema de las fichas (content collection)
src/content/plantas/   fichas generadas, una por especie
src/pages/             listado (/), ficha de especie (/catalogo/<especie>/) y créditos (/creditos/)
var/                   base de datos y caché local (ignorada por git)
```

## Créditos y atribución

Las láminas CC BY y CC BY-SA obligan a atribuir allí donde se muestran. El sitio lo hace en dos sitios:

- **En cada ficha**, bajo cada lámina: autor, obra, año, número de lámina, licencia con enlace y fuente.
- **En [`/creditos/`](src/pages/creditos.astro)**, una página global agrupada por obra: las láminas que exigen atribución aparecen una a una; las de dominio público, en una lista desplegable. También cita a GBIF, Wikidata, Wikimedia Commons y BHL.

Si reutilizas una imagen fuera de esta web, la atribución que debes copiar está en su ficha (`artist`, `work`, `license`, `source_url`).

## Licencias

- **Código**: [MIT](LICENSE).
- **Fichas del catálogo** (`src/content/plantas/`, los metadatos curados): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.es).
- **Imágenes**: cada lámina conserva su licencia original (dominio público, CC0, CC BY o CC BY-SA), indicada en su ficha.

Detalles y datos de terceros en [`LICENSE-DATA.md`](LICENSE-DATA.md).

## Por hacer

- [ ] Procesar el resto de colecciones: Curtis's Botanical Magazine, Flora Batava, *Les Liliacées*, Flora de Filipinas (Blanco) y Thomé.
- [ ] Revisar `var/revision.csv`: unas 230 láminas en revisión, la mayoría de BHL sin nombre detectado en la página.
- [ ] Nombres comunes en español que faltan (Wikidata no los tiene para muchas especies).
- [ ] Floriografía: significado de cada planta, como capa aparte del catálogo.
- [ ] Datos de jardín para clima mediterráneo: floración, sol, riego, rusticidad.
- [ ] Filtros por color en la web, usando la paleta que ya se calcula para cada lámina.
- [ ] Dominio propio para las imágenes en R2 y despliegue en Cloudflare Pages.
