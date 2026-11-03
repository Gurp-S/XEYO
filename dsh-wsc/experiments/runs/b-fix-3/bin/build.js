#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { startWatch } from '../lib/watch.js';

function describe(report) {
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`;
}

function writeReport(report, opts) {
  process.stdout.write(opts.json ? `${JSON.stringify(report)}\n` : describe(report));
}

function writeError(error) {
  process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
}

async function runWatch(opts) {
  const handle = await startWatch(opts, {
    onReport: (report) => writeReport(report, opts),
    onError: writeError,
  });
  process.stdout.write(`watching ${opts.src}\n`);
  await new Promise((resolve) => {
    const stop = () => handle.close().then(resolve, resolve);
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
  });
  return 0;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) return runWatch(opts);
  writeReport(await build(opts), opts);
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    writeError(error);
    process.exitCode = 1;
  },
);
