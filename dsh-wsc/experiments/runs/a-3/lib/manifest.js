import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './atomic.js';

export const MANIFEST_VERSION = 2;

export function emptyManifest() {
  return { version: MANIFEST_VERSION, files: {} };
}

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeEntry(entry) {
  if (!isRecord(entry)) return null;
  if (typeof entry.key !== 'string' || !entry.key) return null;
  const deps = {};
  if (isRecord(entry.deps)) {
    for (const [dep, fingerprint] of Object.entries(entry.deps)) {
      if (typeof fingerprint === 'string') deps[dep] = fingerprint;
    }
  }
  const out = Array.isArray(entry.out) ? entry.out.filter((p) => typeof p === 'string' && p) : [];
  return { key: entry.key, deps, out };
}

// A manifest is a cache, never the source of truth: every entry that cannot be
// trusted is dropped, so a truncated or hand-edited manifest heals itself on
// the next build instead of poisoning it.
export function normalizeManifest(raw) {
  const manifest = emptyManifest();
  if (!isRecord(raw) || !isRecord(raw.files)) return manifest;
  for (const [rel, entry] of Object.entries(raw.files)) {
    const normalized = normalizeEntry(entry);
    if (normalized) manifest.files[rel] = normalized;
  }
  return manifest;
}

export async function loadManifest(file) {
  try {
    return normalizeManifest(JSON.parse(await readFile(file, 'utf8')));
  } catch {
    return emptyManifest();
  }
}

export async function saveManifest(file, manifest) {
  const body = JSON.stringify({ version: MANIFEST_VERSION, files: manifest.files }, null, 2);
  await writeFileAtomic(file, `${body}\n`);
}
