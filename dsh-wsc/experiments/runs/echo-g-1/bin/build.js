#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchSources } from '../lib/watch.js';

function format(report) {
  const removed = report.removed.length ? `, removed ${report.removed.length}` : '';
  return `built ${report.built.length}, skipped ${report.skipped.length}${removed} in ${report.durationMs}ms\n`;
}

function emit(report, opts) {
  if (opts.json) process.stdout.write(`${JSON.stringify(report)}\n`);
  else process.stdout.write(format(report));
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (!opts.watch) {
    emit(await build(opts), opts);
    return 0;
  }
  const session = await watchSources(opts, {
    onReport: (report) => emit(report, opts),
    onError: (error) => {
      process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    },
  });
  const stop = () => {
    session.close();
    process.exit(0);
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  return null;
}

main().then(
  (code) => {
    if (code !== null) process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
