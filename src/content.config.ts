import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

// Fichas generadas por `python -m catalogo export` (una por especie aceptada en GBIF)
const color = z.object({ hex: z.string(), share: z.number() });

const images = z.object({
  thumb: z.string(),
  medium: z.string(),
  full: z.string(),
  width: z.number(),
  height: z.number(),
  formats: z.array(z.string()),
});

const illustration = z.object({
  id: z.string(),
  pageid: z.number(),
  original_name: z.string().nullable(),
  taxon_note: z.string().nullable(),
  multi_species: z.boolean(),
  other_taxa: z.array(z.string()),
  artist: z.string().nullable(),
  work: z.string(),
  source: z.string(),
  origin: z.enum(['commons', 'bhl']),
  plate: z.string().nullable(),
  year: z.number().nullable(),
  license: z.string(),
  license_url: z.string().nullable(),
  share_alike: z.boolean(),
  attribution_required: z.boolean(),
  credit: z.string().nullable(),
  source_url: z.string(),
  file_title: z.string(),
  needs_review: z.boolean(),
  alternates: z.array(z.string()),
  palette: z.array(color),
  images: images.nullable(),
});

const plantas = defineCollection({
  loader: glob({ pattern: '*.json', base: './src/content/plantas' }),
  schema: z.object({
    taxon: z.object({
      accepted: z.string(),
      authorship: z.string().nullable(),
      rank: z.string(),
      genus: z.string().nullable(),
      family: z.string().nullable(),
      gbif_id: z.number(),
      wikidata: z.string().nullable(),
      common_es: z.array(z.string()),
      original_names: z.array(z.string()),
    }),
    illustrations: z.array(illustration).min(1),
  }),
});

export const collections = { plantas };
