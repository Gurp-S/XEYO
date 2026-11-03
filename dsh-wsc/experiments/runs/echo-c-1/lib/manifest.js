import { readFile, writeFile } from 'node:fs/promises';

export const MANIFEST_VERSION = 2;

// The raw manifest, whatever its version: used to clean up outputs that a
// previous run produced even when its entries can no longer be trusted.
export async function loadRawManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    if (!parsed || typeof parsed !== 'object' || !parsed.files) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function loadManifest(file) {
  const parsed = await loadRawManifest(file);
  return parsed && parsed.version === MANIFEST_VERSION ? parsed : null;
}

export async function saveManifest(file, manifest) {
  await writeFile(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
