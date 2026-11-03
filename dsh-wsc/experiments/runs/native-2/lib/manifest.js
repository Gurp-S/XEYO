import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeFiles(files) {
  const normalized = Object.create(null);
  if (!isPlainObject(files)) return normalized;
  for (const [rel, entry] of Object.entries(files)) {
    if (!isPlainObject(entry) || typeof entry.key !== 'string') continue;
    const deps = Object.create(null);
    if (isPlainObject(entry.deps)) {
      for (const [dep, fingerprint] of Object.entries(entry.deps)) {
        if (typeof fingerprint === 'string') deps[dep] = fingerprint;
      }
    }
    const out = Array.isArray(entry.out) ? entry.out.filter((name) => typeof name === 'string' && name !== '') : [];
    normalized[rel] = { key: entry.key, deps, out };
  }
  return normalized;
}

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    if (!isPlainObject(parsed) || parsed.version !== MANIFEST_VERSION) return null;
    return { version: MANIFEST_VERSION, files: normalizeFiles(parsed.files) };
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  const dir = path.dirname(file);
  const temp = path.join(dir, `.${path.basename(file)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`);
  await mkdir(dir, { recursive: true });
  try {
    await writeFile(temp, `${JSON.stringify(manifest, null, 2)}\n`);
    await rename(temp, file);
  } catch (error) {
    await unlink(temp).catch(() => {});
    throw error;
  }
}
