import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

let counter = 0;

const RETRYABLE = new Set(['EPERM', 'EACCES', 'EBUSY', 'EEXIST']);

async function renameWithRetry(from, to) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await rename(from, to);
      return;
    } catch (error) {
      if (attempt >= 5 || !RETRYABLE.has(error?.code)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 10 * (attempt + 1)));
    }
  }
}

/**
 * Write `data` to `file` through a temporary sibling plus an atomic rename.
 *
 * A crash therefore leaves either the previous complete file or the new
 * complete file, never a truncated one: the manifest cannot be half-written.
 */
export async function writeFileAtomic(file, data) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  counter += 1;
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${counter}.tmp`);
  try {
    await writeFile(tmp, data);
    await renameWithRetry(tmp, file);
  } catch (error) {
    await rm(tmp, { force: true }).catch(() => {});
    throw error;
  }
}
