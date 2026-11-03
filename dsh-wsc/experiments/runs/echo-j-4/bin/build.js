#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function printReport(report, opts) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
    return;
  }
  const suffix = report.dryRun ? ' (dry run)' : '';
  process.stdout.write(
    `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms${suffix}\n`,
  );
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) {
    const watcher = watchBuild(opts, process.cwd(), (report) => {
      if (report.error) {
        const message = report.error instanceof Error ? report.error.message : String(report.error);
        process.stderr.write(`build failed: ${message}\n`);
        return;
      }
      printReport(report, opts);
    });
    await watcher.run();
    process.stdout.write(`watching ${opts.src}\n`);
    return undefined;
  }
  printReport(await build(opts), opts);
  return 0;
}

main().then(
  (code) => {
    if (code === undefined) return;
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
