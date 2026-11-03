import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { writeAtomic } from './atomic.js';

export const MANIFEST_VERSION = 2;

export function emptyManifest() {
  return { version: MANIFEST_VERSION, files: {} };
}

// An unreadable, truncated or foreign-version manifest is not an error: it carries no
// usable state, so every source is simply built again.
export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  if (parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object') return null;
  return { version: MANIFEST_VERSION, files: parsed.files };
}

export async function saveManifest(file, manifest) {
  await writeAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}

// A recorded output that is gone means the output tree no longer matches the
// manifest, so the source that owns it has to be built again.
export async function outputsMissing(entry, outDir) {
  for (const rel of entry?.out ?? []) {
    try {
      await stat(path.join(outDir, rel));
    } catch {
      return true;
    }
  }
  return false;
}
