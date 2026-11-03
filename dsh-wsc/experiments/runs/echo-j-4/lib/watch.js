import { watch as watchDir } from 'node:fs';
import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { build } from './build.js';

const DEBOUNCE_MS = 60;
const POLL_MS = 400;

async function signature(dir) {
  const lines = [];
  const walk = async (abs, rel) => {
    let entries;
    try {
      entries = await readdir(abs, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const child = path.join(abs, entry.name);
      const childRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await walk(child, childRel);
      else {
        try {
          const info = await stat(child);
          lines.push(`${childRel}:${info.size}:${info.mtimeMs}`);
        } catch {
          // Vanished between readdir and stat: the next scan reports the absence.
        }
      }
    }
  };
  await walk(dir, '');
  return lines.sort().join('\n');
}

// Recursive fs.watch is the fast path; where the platform cannot do it, a polling
// snapshot of the tree is the fallback. Either way the callback only says "look
// again" — the build itself decides what actually changed, by content.
function watchSources(dir, onChange) {
  let timer = null;
  const fire = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      onChange();
    }, DEBOUNCE_MS);
  };
  let watcher = null;
  try {
    watcher = watchDir(dir, { recursive: true }, fire);
    watcher.on('error', () => {});
  } catch {
    watcher = null;
  }
  let poll = null;
  if (!watcher) {
    let last = null;
    poll = setInterval(async () => {
      const now = await signature(dir);
      if (last !== null && now !== last) fire();
      last = now;
    }, POLL_MS);
    signature(dir).then((now) => {
      last = now;
    }, () => {});
  }
  return {
    close() {
      if (timer) clearTimeout(timer);
      timer = null;
      if (poll) clearInterval(poll);
      poll = null;
      watcher?.close();
      watcher = null;
    },
  };
}

// Rebuilds are serialised: a change that lands mid-build is folded into exactly one
// follow-up build instead of racing the one in flight.
export function watchBuild(opts, cwd, onReport) {
  let running = false;
  let queued = false;
  let closed = false;

  const run = async () => {
    if (closed) return;
    if (running) {
      queued = true;
      return;
    }
    running = true;
    do {
      queued = false;
      try {
        onReport(await build(opts, cwd));
      } catch (error) {
        onReport({ error });
      }
    } while (queued && !closed);
    running = false;
  };

  const sources = watchSources(path.resolve(cwd, opts.src), run);
  const stop = () => {
    closed = true;
    sources.close();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  return { run, stop };
}
