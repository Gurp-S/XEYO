#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { runWatch } from '../lib/watch.js';

function summarize(report) {
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }

  const print = (report) => {
    if (report.error) {
      process.stderr.write(`build failed: ${report.error.message}\n`);
      return;
    }
    process.stdout.write(opts.json ? `${JSON.stringify(report)}\n` : summarize(report));
  };

  if (opts.watch) {
    await runWatch(opts, process.cwd(), {
      emit: print,
      notice: () => {
        const line = `watching ${opts.src} for changes\n`;
        if (opts.json) process.stderr.write(line);
        else process.stdout.write(line);
      },
    });
    return 0;
  }

  print(await build(opts));
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${error?.message ?? error}\n`);
    process.exitCode = 1;
  },
);
