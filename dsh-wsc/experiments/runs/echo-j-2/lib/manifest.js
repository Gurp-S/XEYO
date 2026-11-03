import { readFile, writeFile } from 'node:fs/promises';

export const MANIFEST_VERSION = 2;

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return parsed && parsed.version === MANIFEST_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  await writeFile(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
