import { readFile, writeFile, rename, unlink } from 'node:fs/promises';

export const MANIFEST_VERSION = 2;

const EMPTY = () => ({ version: MANIFEST_VERSION, files: {} });

function valid(parsed) {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  if (parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
  for (const entry of Object.values(parsed.files)) {
    if (!entry || typeof entry !== 'object') return null;
    if (typeof entry.key !== 'string') return null;
    if (!entry.deps || typeof entry.deps !== 'object' || Array.isArray(entry.deps)) return null;
    if (!Array.isArray(entry.out) || entry.out.some((name) => typeof name !== 'string')) return null;
  }
  return parsed;
}

/**
 * A manifest is a cache, never a source of truth: a missing, truncated or
 * hand-edited file degrades to "nothing is cached" instead of aborting the
 * build. A mismatched version rebuilds everything, which is what a format
 * change means anyway.
 */
export async function loadManifest(file) {
  let raw;
  try {
    raw = await readFile(file, 'utf8');
  } catch {
    return { manifest: EMPTY(), status: 'absent' };
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { manifest: EMPTY(), status: 'corrupt' };
  }
  const checked = valid(parsed);
  if (!checked) return { manifest: EMPTY(), status: parsed?.version === MANIFEST_VERSION ? 'corrupt' : 'stale-version' };
  return { manifest: checked, status: 'ok' };
}

/** Write via a temp file + rename so a crash cannot leave a half-written manifest. */
export async function saveManifest(file, manifest) {
  const tmp = `${file}.tmp`;
  await writeFile(tmp, `${JSON.stringify(manifest, null, 2)}\n`);
  try {
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
