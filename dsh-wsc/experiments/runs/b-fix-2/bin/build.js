#!/usr/bin/env node
import { build, watch, parseArgs, USAGE } from '../lib/build.js';

function write(report, json) {
  if (json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } else if (report.error) {
    process.stderr.write(`build failed: ${report.error}\n`);
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
    write(await build(opts), opts.json);
    return 0;
  }

  // Watch mode never exits on its own: the first report covers the initial
  // build, then one report per rebuild. A failed rebuild is reported and the
  // watcher keeps running, so the next edit gets a chance to succeed.
  let stop = () => {};
  const done = new Promise((resolve) => {
    process.once('SIGINT', resolve);
    process.once('SIGTERM', resolve);
  });
  stop = await watch(opts, process.cwd(), (report) => write(report, opts.json));
  await done;
  stop();
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
