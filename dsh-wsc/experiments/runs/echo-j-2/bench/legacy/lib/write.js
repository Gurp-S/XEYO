import { mkdir, rename, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

// Write via a temporary file plus rename so an interrupted build can never
// leave a half-written output behind.
export async function writeAtomic(abs, content) {
  await mkdir(path.dirname(abs), { recursive: true });
  const tmp = `${abs}.${process.pid}.${Date.now()}.tmp`;
  try {
    await writeFile(tmp, content);
    await rename(tmp, abs);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
