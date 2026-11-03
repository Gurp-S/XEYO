import { watch as fsWatch } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { build, formatReport, walk } from './build.js';

export const WATCH_DEBOUNCE_MS = 50;

function message(error) {
  return error instanceof Error ? error.message : String(error);
}

function isInside(parent, child) {
  const rel = path.relative(parent, child);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

/**
 * Build once, then rebuild after every change under the source directory.
 *
 * Every directory is watched on its own so the behaviour does not depend on
 * the platform supporting recursive watches; directories that appear later are
 * picked up on the next pass. Resolves with an exit code when the process is
 * asked to stop or the watch setup itself fails.
 */
export function watch(opts, cwd = process.cwd(), io = {}) {
  const write = io.out ?? ((text) => process.stdout.write(text));
  const writeErr = io.err ?? ((text) => process.stderr.write(text));
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);

  return new Promise((resolve) => {
    const watchers = new Map();
    let timer = null;
    let running = false;
    let queued = false;
    let stopped = false;
    let settled = false;
    let exitCode = 0;

    const finish = (code) => {
      if (settled) return;
      settled = true;
      resolve(code);
    };

    const closeAll = () => {
      for (const watcher of watchers.values()) {
        try {
          watcher.close();
        } catch {
          // The directory is already gone; nothing left to release.
        }
      }
      watchers.clear();
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const detach = () => {
      process.off('SIGINT', onSignal);
      process.off('SIGTERM', onSignal);
    };

    const stop = (code = 0) => {
      if (stopped) return;
      stopped = true;
      exitCode = code;
      closeAll();
      detach();
      if (!running) finish(exitCode);
    };

    const onSignal = () => stop(0);

    const schedule = () => {
      if (stopped) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        void run();
      }, WATCH_DEBOUNCE_MS);
    };

    const onChange = (dir, filename) => {
      if (stopped) return;
      if (filename) {
        const abs = path.resolve(dir, filename.toString());
        // The build's own output must never trigger another build.
        if (abs === manifestPath || abs === outDir || isInside(outDir, abs)) return;
      }
      schedule();
    };

    const syncDirs = async () => {
      let files;
      try {
        files = await walk(srcDir);
      } catch {
        return;
      }
      const dirs = new Set([srcDir]);
      for (const rel of files) dirs.add(path.resolve(srcDir, path.posix.dirname(rel)));
      for (const dir of dirs) {
        if (watchers.has(dir)) continue;
        try {
          const watcher = fsWatch(dir, (event, filename) => onChange(dir, filename));
          watcher.on('error', () => {
            try {
              watcher.close();
            } catch {
              // Already closed.
            }
            watchers.delete(dir);
          });
          watchers.set(dir, watcher);
        } catch (error) {
          // A directory removed between the scan and the watch is not an error.
          if (error && error.code === 'ENOENT') continue;
          throw error;
        }
      }
      for (const [dir, watcher] of [...watchers]) {
        if (dirs.has(dir)) continue;
        try {
          watcher.close();
        } catch {
          // Already closed.
        }
        watchers.delete(dir);
      }
    };

    const run = async () => {
      if (stopped) return;
      if (running) {
        queued = true;
        return;
      }
      running = true;
      try {
        await syncDirs();
        try {
          const report = await build(opts, cwd);
          write(formatReport(report));
        } catch (error) {
          // A broken source stays broken until it is fixed; keep watching.
          writeErr(`build failed: ${message(error)}\n`);
        }
      } catch (error) {
        writeErr(`watch failed: ${message(error)}\n`);
        stopped = true;
        exitCode = 1;
      } finally {
        running = false;
        if (stopped) {
          closeAll();
          detach();
          finish(exitCode);
        } else if (queued) {
          queued = false;
          schedule();
        }
      }
    };

    process.on('SIGINT', onSignal);
    process.on('SIGTERM', onSignal);

    void (async () => {
      try {
        await stat(srcDir);
      } catch {
        writeErr(`watch failed: source directory does not exist: ${srcDir}\n`);
        stopped = true;
        exitCode = 1;
        closeAll();
        detach();
        finish(exitCode);
        return;
      }
      await run();
      if (!stopped) write(`watching ${opts.src} -> ${opts.out} (ctrl-c to stop)\n`);
    })();
  });
}
