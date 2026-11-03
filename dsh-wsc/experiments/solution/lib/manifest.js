import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return parsed && parsed.version === MANIFEST_VERSION && parsed.files ? parsed : null;
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  const tmp = `${file}.${process.pid}.tmp`;
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(tmp, `${JSON.stringify(manifest, null, 2)}\n`);
  await rename(tmp, file);
}
