import { watch } from 'node:fs';
import path from 'node:path';

// Coalesces bursts of filesystem events into one callback. `ignore` receives a
// source-root relative, slash separated path and returns true to drop it.
export function watchSources(root, onChange, options = {}) {
  const debounceMs = options.debounceMs ?? 60;
  const ignore = options.ignore ?? (() => false);
  let timer = null;
  let closed = false;

  const watcher = watch(root, { recursive: true }, (_event, filename) => {
    if (closed) return;
    const name = filename ? String(filename).split(path.sep).join('/') : null;
    if (name && ignore(name)) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (!closed) onChange(name);
    }, debounceMs);
    timer.unref?.();
  });
  watcher.on('error', (error) => {
    if (!closed) options.onError?.(error);
  });

  return {
    close() {
      if (closed) return;
      closed = true;
      if (timer) clearTimeout(timer);
      timer = null;
      watcher.close();
    },
  };
}
