import { open, readFile, rename, unlink } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// Anything that is not a well-formed v2 manifest is treated as absent: the build
// then rebuilds from scratch instead of trusting a shape it cannot read.
export function normalizeManifest(parsed) {
  if (!isPlainObject(parsed) || parsed.version !== MANIFEST_VERSION) return null;
  if (!isPlainObject(parsed.files)) return null;
  const files = Object.create(null);
  for (const [rel, entry] of Object.entries(parsed.files)) {
    if (!isPlainObject(entry) || typeof entry.key !== 'string') continue;
    const deps = Object.create(null);
    if (isPlainObject(entry.deps)) {
      for (const [dep, key] of Object.entries(entry.deps)) {
        if (typeof key === 'string') deps[dep] = key;
      }
    }
    const out = Array.isArray(entry.out)
      ? entry.out.filter((name) => typeof name === 'string' && name !== '')
      : [rel];
    files[rel] = { key: entry.key, deps, out };
  }
  return { version: MANIFEST_VERSION, files };
}

export async function loadManifest(file) {
  try {
    return normalizeManifest(JSON.parse(await readFile(file, 'utf8')));
  } catch {
    return null;
  }
}

// Write beside the target and rename over it, so an interruption leaves either the
// previous manifest or the new one, never a torn file under the real name.
export async function saveManifest(file, manifest) {
  const text = `${JSON.stringify(manifest, null, 2)}\n`;
  const dir = path.dirname(file);
  const temp = path.join(dir, `.${path.basename(file)}.${process.pid}.${Date.now().toString(36)}.tmp`);
  const handle = await open(temp, 'w');
  try {
    await handle.writeFile(text);
    await handle.sync();
  } catch (error) {
    await handle.close().catch(() => {});
    await unlink(temp).catch(() => {});
    throw error;
  }
  await handle.close();
  try {
    await rename(temp, file);
  } catch (error) {
    await unlink(temp).catch(() => {});
    throw error;
  }
}
