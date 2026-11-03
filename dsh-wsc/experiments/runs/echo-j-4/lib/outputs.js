import { mkdir, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { mapLimit } from './pool.js';

function isInside(root, rel) {
  if (typeof rel !== 'string' || rel === '') return false;
  const back = path.relative(root, path.resolve(root, rel));
  return back !== '' && !back.startsWith('..') && !path.isAbsolute(back);
}

export async function outputsPresent(outDir, names) {
  if (!Array.isArray(names) || names.length === 0) return false;
  for (const name of names) {
    if (!isInside(outDir, name)) return false;
    try {
      if (!(await stat(path.join(outDir, name))).isFile()) return false;
    } catch {
      return false;
    }
  }
  return true;
}

export async function writeOutputs(outDir, outputs, limit) {
  const entries = [...outputs];
  await mapLimit(entries, limit, async ([rel, content]) => {
    const abs = path.join(outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
}

export async function removeOutputs(outDir, names) {
  for (const name of names) {
    if (!isInside(outDir, name)) continue;
    await rm(path.join(outDir, name), { force: true });
  }
}
