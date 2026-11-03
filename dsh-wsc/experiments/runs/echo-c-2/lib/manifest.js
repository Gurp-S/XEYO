import { readFile } from 'node:fs/promises';
import { writeAtomic } from './fsutil.js';

export const MANIFEST_VERSION = 2;

function valid(parsed) {
  return (
    parsed &&
    typeof parsed === 'object' &&
    parsed.version === MANIFEST_VERSION &&
    parsed.files &&
    typeof parsed.files === 'object' &&
    !Array.isArray(parsed.files)
  );
}

// An unreadable, malformed or older manifest is treated as absent: the build
// then redoes the work instead of trusting fingerprints it cannot verify.
export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return valid(parsed) ? { version: MANIFEST_VERSION, files: { ...parsed.files } } : null;
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  await writeAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`);
}
