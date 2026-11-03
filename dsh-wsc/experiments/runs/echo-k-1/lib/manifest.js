import { readFile, rename, writeFile } from 'node:fs/promises';

export const MANIFEST_VERSION = 2;

function isEntry(value) {
  if (!value || typeof value !== 'object') return false;
  if (typeof value.key !== 'string') return false;
  if (value.deps !== undefined) {
    if (!value.deps || typeof value.deps !== 'object' || Array.isArray(value.deps)) return false;
    if (Object.values(value.deps).some((dep) => typeof dep !== 'string')) return false;
  }
  if (value.out !== undefined) {
    if (!Array.isArray(value.out)) return false;
    if (value.out.some((rel) => typeof rel !== 'string')) return false;
  }
  return true;
}

// The manifest is a cache, never a source of truth. Anything that is not a
// complete v2 manifest — truncated JSON, a bare version stamp, a half-shaped
// entry — is discarded, which costs one full rebuild and never a wrong output.
export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!parsed || parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
  for (const entry of Object.values(parsed.files)) {
    if (!isEntry(entry)) return null;
  }
  return parsed;
}

// Write-then-rename: a reader never observes a half-written manifest, so a
// crash mid-build cannot leave a torn file for the next build to parse.
export async function saveManifest(file, manifest) {
  const body = `${JSON.stringify(manifest, null, 2)}\n`;
  const temp = `${file}.tmp`;
  await writeFile(temp, body);
  await rename(temp, file);
}
