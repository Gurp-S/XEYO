import {
  normalizePetCatalog,
  normalizePetManifest,
} from './PetManifest';
import type {
  LoadedPetManifest,
  PetCatalog,
  PetCatalogEntry,
} from './types';
import {
  DEFAULT_XEYO_PET_BASE,
  DEFAULT_XEYO_PET_MANIFEST,
} from './types';

export type LoadedPetCatalog = {
  catalog: PetCatalog;
  entries: PetCatalogEntry[];
  manifests: Map<string, LoadedPetManifest>;
};

async function readJson(url: string): Promise<unknown> {
  const response = await fetch(url, {cache: 'no-cache'});
  if (!response.ok) {
    throw new Error(`Unable to load XeyoPet resource (${response.status}): ${url}`);
  }
  return response.json() as Promise<unknown>;
}

function resolveUrl(path: string, rootUrl: string): string {
  return new URL(path, new URL(rootUrl, window.location.origin)).href;
}

export async function loadPetCatalog(
  catalogUrl = `${DEFAULT_XEYO_PET_BASE}/catalog.json`,
): Promise<LoadedPetCatalog> {
  const catalog = normalizePetCatalog(await readJson(catalogUrl));
  const entries = catalog.pets.filter(entry => entry.enabled !== false);
  const manifests = new Map<string, LoadedPetManifest>();

  await Promise.all(
    entries.map(async entry => {
      const manifestUrl = resolveUrl(entry.manifestPath, catalogUrl);
      const loaded = normalizePetManifest(await readJson(manifestUrl), manifestUrl);
      if (loaded.manifest.id !== entry.id) {
        throw new Error(
          `Pet catalog id mismatch: ${entry.id} != ${loaded.manifest.id}`,
        );
      }
      manifests.set(entry.id, loaded);
    }),
  );

  if (manifests.size === 0) {
    throw new Error('XeyoPet catalog has no enabled manifests');
  }
  return {catalog, entries, manifests};
}

export async function loadFirstPetManifest(
  baseUrl = DEFAULT_XEYO_PET_BASE,
): Promise<LoadedPetManifest> {
  const manifestUrl = `${baseUrl.replace(/\/$/, '')}/${DEFAULT_XEYO_PET_MANIFEST}`;
  return normalizePetManifest(await readJson(manifestUrl), manifestUrl);
}

export function selectPetManifest(
  loaded: LoadedPetCatalog,
  selectedId?: string,
): LoadedPetManifest {
  const id = selectedId ?? loaded.catalog.defaultPetId ?? loaded.entries[0]?.id;
  const manifest = id ? loaded.manifests.get(id) : undefined;
  if (manifest) return manifest;
  const first = loaded.entries[0] && loaded.manifests.get(loaded.entries[0].id);
  if (!first) throw new Error('No usable XeyoPet manifest is available');
  return first;
}

export async function loadSelectedPet(
  selectedId?: string,
  catalogUrl = `${DEFAULT_XEYO_PET_BASE}/catalog.json`,
): Promise<LoadedPetManifest> {
  try {
    return selectPetManifest(await loadPetCatalog(catalogUrl), selectedId);
  } catch (catalogError) {
    try {
      return await loadFirstPetManifest();
    } catch (manifestError) {
      const catalogMessage = catalogError instanceof Error ? catalogError.message : String(catalogError);
      const manifestMessage = manifestError instanceof Error ? manifestError.message : String(manifestError);
      throw new Error(`${catalogMessage}; fallback failed: ${manifestMessage}`);
    }
  }
}
