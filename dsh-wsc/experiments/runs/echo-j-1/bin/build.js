#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function printReport(report, json) {
  if (json) {
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
  if (opts.watch) {
    const controller = new AbortController();
    const stop = () => controller.abort();
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
    try {
      await watchBuild(opts, {
        onReport: (report) => printReport(report, opts.json),
        onError: (error) => {
          process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
        },
        signal: controller.signal,
      });
    } finally {
      process.removeListener('SIGINT', stop);
      process.removeListener('SIGTERM', stop);
    }
    return 0;
  }
  printReport(await build(opts), opts.json);
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
