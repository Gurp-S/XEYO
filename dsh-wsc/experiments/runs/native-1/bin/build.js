#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function printReport(report, json) {
  if (json) {
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
  if (opts.watch) {
    const watcher = await watchBuild(opts, process.cwd(), {
      onReport: (report) => printReport(report, opts.json),
      onError: (error) => {
        process.stderr.write(
          `build failed: ${error instanceof Error ? error.message : String(error)}\n`,
        );
      },
    });
    const stop = () => {
      watcher.close().then(() => process.exit(0));
    };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
    return null; // stay alive until a signal arrives
  }
  const report = await build(opts);
  printReport(report, opts.json);
  return 0;
}

main().then(
  (code) => {
    if (code !== null) process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
