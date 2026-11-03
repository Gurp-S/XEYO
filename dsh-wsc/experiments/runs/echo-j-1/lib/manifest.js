import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    // Missing, unreadable or truncated manifests are all recoverable: the
    // caller treats this as a cold build instead of crashing.
    return null;
  }
  if (!isObject(parsed) || parsed.version !== MANIFEST_VERSION || !isObject(parsed.files)) {
    return null;
  }
  return parsed;
}

// Write through a temporary file in the same directory and rename it into
// place. A process killed mid-write leaves the previous manifest intact
// instead of a truncated JSON document.
export async function saveManifest(file, manifest) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(
    dir,
    `.${path.basename(file)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`,
  );
  const data = `${JSON.stringify(manifest, null, 2)}\n`;
  try {
    await writeFile(tmp, data);
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
