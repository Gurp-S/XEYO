#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { startWatch } from '../lib/watch.js';

function print(report, json) {
  if (report.error) {
    process.stderr.write(`build failed: ${report.error}\n`);
    return;
  }
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
    const session = startWatch(opts, process.cwd(), (report) => print(report, opts.json));
    const stop = () => {
      session.close();
      process.exit(0);
    };
    process.on('SIGINT', stop);
    process.on('SIGTERM', stop);
    return null;
  }
  print(await build(opts), opts.json);
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
