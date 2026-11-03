import { open, readFile, rename, unlink, mkdir } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isStringArray(value) {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

// A manifest is only trusted when it has the exact shape this version writes.
// Anything else (truncated, hand-edited, older format) is treated as absent so
// the build falls back to a full rebuild instead of crashing.
export function normalizeManifest(parsed) {
  if (!isPlainObject(parsed) || parsed.version !== MANIFEST_VERSION) return null;
  if (!isPlainObject(parsed.files)) return null;
  const files = {};
  for (const [rel, entry] of Object.entries(parsed.files)) {
    if (!isPlainObject(entry)) return null;
    if (typeof entry.key !== 'string') return null;
    if (!isPlainObject(entry.deps)) return null;
    if (!Object.values(entry.deps).every((value) => typeof value === 'string')) return null;
    if (!isStringArray(entry.out)) return null;
    files[rel] = { key: entry.key, deps: { ...entry.deps }, out: [...entry.out] };
  }
  return { version: MANIFEST_VERSION, files };
}

export async function loadManifest(file) {
  let text;
  try {
    text = await readFile(file, 'utf8');
  } catch {
    return null;
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  return normalizeManifest(parsed);
}

// Write to a sibling temp file and rename over the target, so an interrupted
// build can never leave a half-written manifest behind.
export async function saveManifest(file, manifest) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`);
  const data = `${JSON.stringify(manifest, null, 2)}\n`;
  let handle;
  try {
    handle = await open(tmp, 'w');
    await handle.writeFile(data, 'utf8');
    await handle.sync();
  } finally {
    await handle?.close();
  }
  try {
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
