import { mkdir, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

// A file written in place can be left truncated by an interruption, and a truncated
// manifest crashes the next build. The bytes go to a sibling temp file first and are
// renamed into place, so a reader observes either the old bytes or the new bytes.
export async function writeAtomic(file, content) {
  await mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now().toString(36)}.tmp`;
  try {
    await writeFile(tmp, content);
    await rename(tmp, file);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
}
