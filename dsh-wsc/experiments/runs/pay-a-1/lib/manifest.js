import { mkdir, open, readFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Load a v2 manifest.
 *
 * Anything unreadable, truncated, half-written or shaped differently is treated
 * as "no manifest": the build then plans from scratch instead of crashing. A
 * corrupt manifest can therefore never wedge the build.
 */
export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!isObject(parsed) || parsed.version !== MANIFEST_VERSION || !isObject(parsed.files)) return null;
  const files = {};
  for (const [rel, entry] of Object.entries(parsed.files)) {
    if (!isObject(entry) || typeof entry.key !== 'string') continue;
    files[rel] = {
      key: entry.key,
      deps: isObject(entry.deps) ? entry.deps : {},
      out: Array.isArray(entry.out) ? entry.out.filter((name) => typeof name === 'string') : null,
    };
  }
  return { version: MANIFEST_VERSION, files };
}

/**
 * Write the manifest atomically: a sibling temp file, flushed, then renamed over
 * the target. An interrupted build leaves either the previous manifest or the
 * new one, never a half-written file.
 */
export async function saveManifest(file, manifest) {
  const target = path.resolve(file);
  const dir = path.dirname(target);
  await mkdir(dir, { recursive: true });
  const temp = path.join(dir, `.${path.basename(target)}.${process.pid}.${Date.now().toString(36)}.tmp`);
  const data = `${JSON.stringify(manifest, null, 2)}\n`;
  let handle;
  try {
    handle = await open(temp, 'w');
    await handle.writeFile(data);
    await handle.sync();
  } finally {
    await handle?.close();
  }
  try {
    await rename(temp, target);
  } catch (error) {
    await rm(temp, { force: true });
    throw error;
  }
}
