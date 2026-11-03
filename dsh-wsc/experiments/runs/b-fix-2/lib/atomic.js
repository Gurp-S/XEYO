import { open, rename, unlink, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

// Write a file so that readers only ever observe the old or the new bytes:
// stage a sibling temp file, flush it, then rename over the target. A crash
// mid-write leaves the target untouched instead of truncated.
export async function writeFileAtomic(file, data) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`);
  let handle;
  try {
    handle = await open(tmp, 'w');
    await handle.writeFile(data);
    await handle.sync();
    await handle.close();
    handle = null;
    await rename(tmp, file);
  } catch (error) {
    if (handle) await handle.close().catch(() => {});
    await unlink(tmp).catch(() => {});
    throw error;
  }
}
