import { mkdir, readdir, rename, rm, rmdir, stat, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

// A file is either the old bytes or the new bytes, never a prefix of the new
// bytes: the write lands on a sibling temp path and is renamed into place.
export async function writeFileAtomic(file, data) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`);
  try {
    await writeFile(tmp, data);
    await rename(tmp, file);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
}

export async function removeFile(file) {
  await rm(file, { force: true });
}

// Removes directories left empty by deletions, stopping at the output root.
export async function pruneEmptyDirs(dir, stopAt) {
  const root = path.resolve(stopAt);
  let current = path.resolve(dir);
  while (current !== root && current.startsWith(`${root}${path.sep}`)) {
    try {
      await rmdir(current);
    } catch {
      return;
    }
    current = path.dirname(current);
  }
}

export async function pathExists(file) {
  try {
    await stat(file);
    return true;
  } catch {
    return false;
  }
}

// Every regular file below `dir`, as sorted, slash separated paths relative to
// `base`.
export async function walkFiles(dir, base = dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walkFiles(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}
