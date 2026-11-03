import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    if (!isObject(parsed) || parsed.version !== MANIFEST_VERSION || !isObject(parsed.files)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export async function saveManifest(file, manifest) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const temp = path.join(
    dir,
    `.${path.basename(file)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`,
  );
  try {
    await writeFile(temp, `${JSON.stringify(manifest, null, 2)}\n`);
    await rename(temp, file);
  } catch (error) {
    await rm(temp, { force: true }).catch(() => {});
    throw error;
  }
}
