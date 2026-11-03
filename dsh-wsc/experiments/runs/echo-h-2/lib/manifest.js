import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function usable(parsed) {
  return Boolean(
    parsed &&
      parsed.version === MANIFEST_VERSION &&
      parsed.files &&
      typeof parsed.files === 'object' &&
      !Array.isArray(parsed.files),
  );
}

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return usable(parsed) ? parsed : null;
  } catch {
    // A missing, truncated or corrupt manifest is simply an empty manifest: the
    // next build reconstructs it from the sources.
    return null;
  }
}

export async function saveManifest(file, manifest) {
  await mkdir(path.dirname(path.resolve(file)), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  await writeFile(temp, `${JSON.stringify(manifest, null, 2)}\n`);
  // Rename is atomic on the same filesystem, so a crash either leaves the old
  // manifest or the new one, never a half-written file.
  await rename(temp, file);
}
