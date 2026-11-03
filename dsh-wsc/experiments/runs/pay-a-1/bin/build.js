#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { startWatch } from '../lib/watch.js';

function describe(error) {
  return error instanceof Error ? error.message : String(error);
}

/** One line per build; `--json` keeps the same report, one object per line. */
function report(opts, result) {
  if (opts.json) return `${JSON.stringify(result)}\n`;
  return `built ${result.built.length}, skipped ${result.skipped.length}, removed ${result.removed.length} in ${result.durationMs}ms\n`;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (!opts.watch) {
    process.stdout.write(report(opts, await build(opts)));
    return 0;
  }
  const watcher = startWatch(opts, {
    onReport: (result) => process.stdout.write(report(opts, result)),
    onError: (error) => process.stderr.write(`build failed: ${describe(error)}\n`),
  });
  // Close the watcher and let the event loop drain: no pending output is lost.
  const shutdown = () => watcher.close();
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
  return new Promise(() => {});
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${describe(error)}\n`);
    process.exitCode = 1;
  },
);
