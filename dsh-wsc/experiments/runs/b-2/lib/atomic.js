import { rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

// A reader never observes a partial file: bytes land in a sibling temp file and
// are moved into place in one step, so an interrupted write leaves the previous
// content (or nothing) behind rather than a truncated file.
export async function writeFileAtomic(file, data) {
  const tmp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.tmp`);
  try {
    await writeFile(tmp, data);
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
