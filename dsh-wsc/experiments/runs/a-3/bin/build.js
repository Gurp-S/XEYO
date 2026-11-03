#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function printReport(opts, report) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } else {
    process.stdout.write(
      `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
    );
  }
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
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  await watchBuild(opts, {
    signal: controller.signal,
    onChange: (report, error) => {
      if (error) {
        process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
        return;
      }
      printReport(opts, report);
    },
  });
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
