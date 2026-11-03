import { rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';

let counter = 0;

// Write-to-temp-then-rename: a reader either sees the old file or the complete
// new file, never a half-written one. A build killed mid-write leaves at most a
// stray temp file, which `cleanupTemp` sweeps and which is never mistaken for
// real output.
export async function writeFileAtomic(file, data) {
  const dir = path.dirname(file);
  const base = path.basename(file);
  counter = (counter + 1) % 0x7fffffff;
  const tmp = path.join(dir, `.${base}.${process.pid}.${counter}.tmp`);
  try {
    await writeFile(tmp, data);
    await rename(tmp, file);
  } catch (err) {
    await rm(tmp, { force: true });
    throw err;
  }
}

// A temp file left behind by an interrupted build is not an output: drop it
// while scanning so it can never be reported or hashed.
export function isTempName(name) {
  return name.startsWith('.') && name.endsWith('.tmp');
}
