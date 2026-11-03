import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './atomic.js';

export const MANIFEST_VERSION = 2;

// A manifest that cannot be read or parsed is treated as absent: the next
// build then rebuilds everything instead of crashing on a truncated file.
export async function loadManifest(file) {
  let raw;
  try {
    raw = await readFile(file, 'utf8');
  } catch {
    return null;
  }
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || parsed.version !== MANIFEST_VERSION) return null;
    if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
    return parsed;
  } catch {
    return null;
  }
}

// The manifest is the commit point of a build. Writing it atomically and last
// means an interrupted build leaves the previous manifest readable instead of
// a half-written one that breaks the next run.
export async function saveManifest(file, manifest) {
  await writeFileAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
