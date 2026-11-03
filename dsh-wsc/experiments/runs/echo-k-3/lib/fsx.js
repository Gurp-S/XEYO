import { rm, mkdir, open, rename, rmdir, stat } from 'node:fs/promises';
import path from 'node:path';

// Every write lands through a temporary sibling and a rename, so an
// interruption leaves either the previous file or the complete new one - never
// a half-written file.

export async function writeFileAtomic(abs, bytes) {
  await mkdir(path.dirname(abs), { recursive: true });
  const tmp = `${abs}.${process.pid}.${Math.random().toString(36).slice(2, 10)}.tmp`;
  let handle;
  try {
    handle = await open(tmp, 'w');
    await handle.writeFile(bytes);
    await handle.sync();
    await handle.close();
    handle = undefined;
    await rename(tmp, abs);
  } catch (error) {
    if (handle) await handle.close().catch(() => {});
    await rm(tmp, { force: true }).catch(() => {});
    throw error;
  }
}

export async function removeFile(abs) {
  await rm(abs, { force: true });
}

export function isInside(root, target) {
  const resolvedRoot = path.resolve(root);
  const resolvedTarget = path.resolve(target);
  return resolvedTarget === resolvedRoot || resolvedTarget.startsWith(`${resolvedRoot}${path.sep}`);
}

// Only a definite answer is treated as present; any other error still surfaces,
// so a permission problem is not silently mistaken for a missing output.
export async function pathExists(abs) {
  try {
    await stat(abs);
    return true;
  } catch (error) {
    if (error && error.code === 'ENOENT') return false;
    throw error;
  }
}

export async function pruneEmptyDirs(root, startDir) {
  const resolvedRoot = path.resolve(root);
  let dir = path.resolve(startDir);
  while (isInside(resolvedRoot, dir) && dir !== resolvedRoot) {
    try {
      await rmdir(dir);
    } catch {
      return;
    }
    dir = path.dirname(dir);
  }
}
