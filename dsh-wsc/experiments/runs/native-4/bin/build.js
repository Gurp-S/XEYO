#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function describe(error) {
  return error instanceof Error ? error.message : String(error);
}

function printReport(opts, report) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
    return;
  }
  process.stdout.write(
    `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
  );
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (!opts.watch) {
    printReport(opts, await build(opts));
    return 0;
  }

  // Watch mode reports every rebuild and keeps going after a failed one, so a
  // broken intermediate edit does not end the session. Ctrl-C ends it cleanly.
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  try {
    await watchBuild(opts, {
      build,
      onReport: (report) => printReport(opts, report),
      onError: (error) => process.stderr.write(`build failed: ${describe(error)}\n`),
      signal: controller.signal,
    });
  } finally {
    process.off('SIGINT', stop);
    process.off('SIGTERM', stop);
  }
  return 0;
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
