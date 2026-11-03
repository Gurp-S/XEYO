#!/usr/bin/env node
import { build, parseArgs, USAGE, watch } from '../lib/build.js';

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) {
    await watch(opts);
    return 0;
  }
  const report = await build(opts);
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } else {
    process.stdout.write(
      `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
    );
  }
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
