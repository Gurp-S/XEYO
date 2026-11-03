import { watch } from 'node:fs';
import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { build } from './build.js';

// Editors emit a burst of events for a single save (write, rename, chmod), so
// a change is only acted on once the burst has gone quiet.
export const DEFAULT_DEBOUNCE_MS = 50;

function isInside(parent, child) {
  const rel = path.relative(parent, child);
  return rel === '' || (rel !== '..' && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel));
}

async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

// Every directory the source tree contains, one level at a time. Watching each
// directory individually keeps behaviour identical on platforms where
// `fs.watch({ recursive: true })` is unavailable. Symlinked directories are not
// followed, matching the source walk.
export async function listSourceDirs(root) {
  if (!(await exists(root))) return [];
  const entries = await readdir(root, { withFileTypes: true });
  const dirs = [root];
  for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
    if (entry.isDirectory()) dirs.push(...(await listSourceDirs(path.join(root, entry.name))));
  }
  return dirs;
}

// Rebuild on every source change until `signal` aborts. Resolves after the
// watchers are closed. Build failures are reported through `onError` and do not
// end the loop: a broken source is exactly what the user is about to fix.
export async function watchBuild(opts, options = {}) {
  const {
    cwd = process.cwd(),
    debounceMs = DEFAULT_DEBOUNCE_MS,
    onReport = () => {},
    onError = () => {},
    signal = null,
  } = options;

  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const watchers = new Map();
  let parentWatcher = null;
  let timer = null;
  let running = false;
  let dirty = false;
  let closed = false;
  let resolveDone;
  const done = new Promise((resolve) => {
    resolveDone = resolve;
  });

  // Outputs and manifest bookkeeping must never feed back into the watch loop.
  function isIgnored(abs) {
    if (abs === manifestPath || isInside(outDir, abs)) return true;
    const dir = path.dirname(manifestPath);
    return path.dirname(abs) === dir && path.basename(abs).startsWith(`.${path.basename(manifestPath)}.`);
  }

  async function syncWatchers() {
    const before = [...watchers.keys()].sort().join('\n');
    const dirs = await listSourceDirs(srcDir);
    const wanted = new Set(dirs);
    for (const [dir, watcher] of watchers) {
      if (wanted.has(dir)) continue;
      watcher.close();
      watchers.delete(dir);
    }
    for (const dir of dirs) {
      if (watchers.has(dir)) continue;
      let watcher;
      try {
        watcher = watch(dir, (event, file) => {
          if (file && isIgnored(path.resolve(dir, file.toString()))) return;
          schedule();
        });
      } catch {
        // The directory disappeared between the scan and the watch; the next
        // sync retries.
        continue;
      }
      watcher.on('error', () => {
        watcher.close();
        watchers.delete(dir);
        schedule();
      });
      watchers.set(dir, watcher);
    }
    return before !== [...watchers.keys()].sort().join('\n');
  }

  // A source tree that is removed and recreated is invisible to watchers on its
  // own subdirectories, so the parent is watched as well.
  function watchParent() {
    const parent = path.dirname(srcDir);
    if (parent === srcDir) return;
    try {
      parentWatcher = watch(parent, (event, file) => {
        if (!file || path.resolve(parent, file.toString()) !== srcDir) return;
        schedule();
      });
      parentWatcher.on('error', () => {
        parentWatcher?.close();
        parentWatcher = null;
      });
    } catch {
      parentWatcher = null;
    }
  }

  async function runOnce() {
    if (closed) return;
    if (running) {
      dirty = true;
      return;
    }
    running = true;
    try {
      do {
        dirty = false;
        try {
          onReport(await build(opts, cwd));
        } catch (error) {
          onError(error);
        }
        // A directory created during the build may hold files the walk missed;
        // another pass picks them up. It is cheap: unchanged files are skipped.
        if (await syncWatchers()) dirty = true;
      } while (dirty && !closed);
    } finally {
      running = false;
    }
  }

  function schedule() {
    if (closed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      runOnce().catch((error) => onError(error));
    }, debounceMs);
  }

  function close() {
    if (closed) return;
    closed = true;
    if (timer) clearTimeout(timer);
    timer = null;
    for (const watcher of watchers.values()) watcher.close();
    watchers.clear();
    parentWatcher?.close();
    parentWatcher = null;
    resolveDone();
  }

  if (signal) {
    if (signal.aborted) close();
    else signal.addEventListener('abort', close, { once: true });
  }

  watchParent();
  await syncWatchers();
  await runOnce();
  return done;
}
