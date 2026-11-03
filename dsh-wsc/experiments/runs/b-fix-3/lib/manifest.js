import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return parsed && parsed.version === MANIFEST_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

// Write to a sibling temp file and rename over the target, so an interrupted
// build can never leave a half-written manifest behind.
export async function saveManifest(file, manifest) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.tmp`);
  try {
    await writeFile(tmp, `${JSON.stringify(manifest, null, 2)}\n`);
    await rename(tmp, file);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
}
