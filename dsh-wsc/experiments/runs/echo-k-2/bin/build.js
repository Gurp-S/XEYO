#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function describe(report) {
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms`;
}

function print(report, opts) {
  process.stdout.write(opts.json ? `${JSON.stringify(report)}\n` : `${describe(report)}\n`);
}

function message(error) {
  return error instanceof Error ? error.message : String(error);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (!opts.watch) {
    print(await build(opts), opts);
    return 0;
  }

  const watcher = watchBuild(opts, {
    onReport: (report) => print(report, opts),
    onError: (error) => process.stderr.write(`build failed: ${message(error)}\n`),
  });
  await new Promise((resolve) => {
    const stop = () => resolve();
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
  });
  watcher.close();
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${message(error)}\n`);
    process.exitCode = 1;
  },
);
