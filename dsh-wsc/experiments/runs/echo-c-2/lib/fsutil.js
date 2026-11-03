import { readdir, mkdir, rename, unlink, writeFile, stat } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import path from 'node:path';

// Windows can refuse a rename/unlink while a scanner or editor holds the
// handle; those errors are transient and worth a short retry.
const TRANSIENT = new Set(['EPERM', 'EACCES', 'EBUSY', 'ENOTEMPTY']);

let counter = 0;

function tmpName(file) {
  counter += 1;
  return `.${path.basename(file)}.${process.pid}.${counter}.${Math.random().toString(36).slice(2)}.tmp`;
}

export async function withRetry(run, attempts = 4) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await run();
    } catch (error) {
      if (attempt >= attempts - 1 || !TRANSIENT.has(error?.code)) throw error;
      await delay(10 * (attempt + 1));
    }
  }
}

// Symbolic links are skipped on purpose: walk() only ever reports real files
// and real directories, so a link cycle can never trap the traversal.
export async function walk(dir, base = dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

export async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

export async function anyMissing(dir, names) {
  for (const name of names) {
    if (!(await exists(path.join(dir, name)))) return true;
  }
  return false;
}

// Write through a sibling temporary file so a reader either sees the previous
// bytes or the complete new bytes, never a half-written file.
export async function writeAtomic(file, data) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(dir, tmpName(file));
  try {
    await writeFile(tmp, data);
    await withRetry(() => rename(tmp, file));
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}

export async function removeFile(file) {
  try {
    await withRetry(() => unlink(file));
    return true;
  } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
}
