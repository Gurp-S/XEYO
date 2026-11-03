import { mkdir, rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

let counter = 0;

// Write through a sibling temp file and rename into place, so an interrupted
// build can never leave a half-written file behind.
export async function writeFileAtomic(file, data) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  counter += 1;
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${counter}.tmp`);
  try {
    await writeFile(tmp, data);
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
