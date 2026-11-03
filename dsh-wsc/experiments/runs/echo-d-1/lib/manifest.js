import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    if (!parsed || parsed.version !== MANIFEST_VERSION) return null;
    if (!parsed.files || typeof parsed.files !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Write the manifest atomically: a crash can leave the previous manifest or the
 * new one, never a half-written file that breaks the next build.
 */
export async function saveManifest(file, manifest) {
  await mkdir(path.dirname(path.resolve(file)), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  await writeFile(temp, `${JSON.stringify(manifest, null, 2)}\n`);
  await rename(temp, file);
}
