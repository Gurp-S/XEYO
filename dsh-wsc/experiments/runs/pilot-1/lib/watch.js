import { watch as fsWatch } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 60;

function isOutside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative);
}

function isSameOrInside(parent, child) {
  return path.relative(parent, child) === '' || !isOutside(parent, child);
}

function samePath(a, b) {
  return path.relative(a, b) === '';
}

async function collectDirs(root, ignored) {
  const dirs = new Set();
  const visit = async (dir) => {
    if (ignored(dir)) return;
    dirs.add(dir);
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      // Symlinked directories are not followed, matching the build walker.
      if (entry.isDirectory()) await visit(path.join(dir, entry.name));
    }
  };
  await visit(root);
  return dirs;
}

async function watchSources(srcDir, ignored, onChange) {
  const watchers = new Map();
  let timer = null;
  let closed = false;

  const sync = async () => {
    if (closed) return;
    const dirs = await collectDirs(srcDir, ignored);
    if (closed) return;
    for (const [dir, watcher] of watchers) {
      if (!dirs.has(dir)) {
        watcher.close();
        watchers.delete(dir);
      }
    }
    for (const dir of dirs) {
      if (closed) return;
      if (watchers.has(dir)) continue;
      try {
        const watcher = fsWatch(dir, { persistent: true }, (event, filename) => {
          if (closed) return;
          if (filename && ignored(path.resolve(dir, filename.toString()))) return;
          schedule();
        });
        watcher.on('error', () => {
          watcher.close();
          if (watchers.get(dir) === watcher) watchers.delete(dir);
        });
        watchers.set(dir, watcher);
      } catch {
        // The directory vanished between readdir and watch; the next sync
        // will pick up whatever replaced it.
      }
    }
  };

  const schedule = () => {
    if (closed) return;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      sync().then(
        () => {
          if (!closed) onChange();
        },
        () => {},
      );
    }, DEBOUNCE_MS);
  };

  await sync();

  return async () => {
    closed = true;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    for (const watcher of watchers.values()) watcher.close();
    watchers.clear();
  };
}

export async function startWatch(opts, cwd, { onReport, onError } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const manifestTmpPrefix = `.${path.basename(manifestPath)}.`;

  // Do not watch our own output or manifest writes; that would feed the build
  // back into itself when --out or --manifest lives under --src.
  const outInsideSrc = outDir !== srcDir && !isOutside(srcDir, outDir);
  const ignored = (abs) => {
    if (outInsideSrc && isSameOrInside(outDir, abs)) return true;
    if (samePath(abs, manifestPath)) return true;
    const base = path.basename(abs);
    return base.startsWith(manifestTmpPrefix) && base.endsWith('.tmp');
  };

  let closed = false;
  let running = false;
  let pending = false;

  const rebuild = async () => {
    if (closed) return;
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      do {
        pending = false;
        const report = await build(opts, cwd);
        if (!closed) onReport?.(report);
      } while (pending && !closed);
    } finally {
      running = false;
    }
  };

  const rebuildSafely = async () => {
    try {
      await rebuild();
    } catch (error) {
      onError?.(error);
    }
  };

  const closeWatchers = await watchSources(srcDir, ignored, () => {
    void rebuildSafely();
  });

  // Initial build. Mark it as running so events arriving during the build are
  // queued rather than starting a second build concurrently.
  running = true;
  try {
    const report = await build(opts, cwd);
    if (!closed) onReport?.(report);
  } catch (error) {
    await closeWatchers();
    throw error;
  } finally {
    running = false;
  }
  if (pending) void rebuildSafely();

  return async () => {
    closed = true;
    await closeWatchers();
  };
}
