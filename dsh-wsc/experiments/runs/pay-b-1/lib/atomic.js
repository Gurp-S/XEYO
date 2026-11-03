import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import path from 'node:path';

/**
 * Write `data` to `file` so that readers only ever see the old or the new
 * content: the bytes land in a sibling temp file which is then renamed over
 * the destination. An interrupted write leaves the previous file intact.
 */
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
