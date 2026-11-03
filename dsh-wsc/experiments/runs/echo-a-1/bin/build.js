#!/usr/bin/env node
import { build, formatReport, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) return watchBuild(opts);
  const report = await build(opts);
  process.stdout.write(formatReport(report, opts.json));
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
