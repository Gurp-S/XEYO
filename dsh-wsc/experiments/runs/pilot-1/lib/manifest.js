import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

function isManifest(value) {
  return (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    value.version === MANIFEST_VERSION &&
    value.files !== null &&
    typeof value.files === 'object' &&
    !Array.isArray(value.files)
  );
}

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    return isManifest(parsed) ? parsed : null;
  } catch {
    // A missing, truncated, or otherwise unusable manifest is equivalent to no
    // manifest: rebuild from scratch instead of trusting a partial file.
    return null;
  }
}

export async function saveManifest(file, manifest) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(
    dir,
    `.${path.basename(file)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`,
  );
  try {
    await writeFile(tmp, `${JSON.stringify(manifest, null, 2)}\n`);
    // Rename is atomic on the same filesystem, so readers never observe a
    // half-written manifest even if the process is interrupted.
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
