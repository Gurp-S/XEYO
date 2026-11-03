import { mkdir, open, readFile, rename, unlink } from 'node:fs/promises';
import path from 'node:path';

export const MANIFEST_VERSION = 2;

export async function loadManifest(file) {
  try {
    const parsed = JSON.parse(await readFile(file, 'utf8'));
    if (!parsed || parsed.version !== MANIFEST_VERSION) return null;
    if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
    return parsed;
  } catch {
    // A missing, truncated, or otherwise unreadable manifest is not fatal:
    // the next build simply starts from an empty manifest.
    return null;
  }
}

/**
 * Replace the manifest atomically. A crash can leave the previous manifest or
 * the complete new one, but never a half-written file at `file`.
 */
export async function saveManifest(file, manifest) {
  const data = `${JSON.stringify(manifest, null, 2)}\n`;
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.${Date.now().toString(36)}.${Math.random()
    .toString(36)
    .slice(2)}.tmp`;

  try {
    const handle = await open(temp, 'w');
    try {
      await handle.writeFile(data, 'utf8');
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temp, file);
  } catch (error) {
    await unlink(temp).catch(() => {});
    throw error;
  }
}
