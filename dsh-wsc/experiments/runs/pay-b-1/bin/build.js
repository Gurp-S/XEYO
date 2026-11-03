#!/usr/bin/env node
import { build, parseArgs, runWatch, USAGE } from '../lib/build.js';

function formatError(error) {
  return error instanceof Error ? error.message : String(error);
}

function reporter(opts) {
  return (report) => {
    if (opts.json) {
      process.stdout.write(`${JSON.stringify(report)}\n`);
      return;
    }
    process.stdout.write(
      `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
    );
  };
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  const print = reporter(opts);
  if (!opts.watch) {
    print(await build(opts));
    return 0;
  }

  const controller = new AbortController();
  const stop = () => controller.abort();
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  try {
    await runWatch(opts, process.cwd(), {
      signal: controller.signal,
      onReport: print,
      onError: (error) => process.stderr.write(`build failed: ${formatError(error)}\n`),
    });
  } finally {
    process.off('SIGINT', stop);
    process.off('SIGTERM', stop);
  }
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${formatError(error)}\n`);
    process.exitCode = 1;
  },
);
