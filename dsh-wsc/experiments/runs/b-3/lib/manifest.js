import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function emptyManifest() {
  return { version: MANIFEST_VERSION, files: {} };
}

export async function loadManifest(file) {
  let raw;
  try {
    raw = await readFile(file, 'utf8');
  } catch {
    return null;
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // A truncated or otherwise unreadable manifest is not fatal: the build
    // simply starts from an empty one and rewrites it.
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return emptyManifest();
  return { version: MANIFEST_VERSION, files: parsed.files };
}

// The manifest is written to a sibling temp file and renamed into place, so an
// interrupted build leaves either the previous manifest or the new one, never
// half of either.
export async function saveManifest(file, manifest) {
  const text = `${JSON.stringify(manifest, null, 2)}\n`;
  const dir = path.dirname(file);
  const tmp = `${file}.${process.pid}.${Date.now().toString(36)}.tmp`;
  await mkdir(dir, { recursive: true });
  try {
    await writeFile(tmp, text);
    await rename(tmp, file);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
}
