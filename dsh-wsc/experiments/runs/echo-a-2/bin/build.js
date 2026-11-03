#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function print(report) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } else {
    process.stdout.write(
      `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
    );
  }
}

let opts;

async function main() {
  opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  print(await build(opts));
  if (!opts.watch) return 0;

  const watcher = watchBuild(opts, process.cwd(), {
    onReport(report, changed) {
      if (!opts.json && changed.length > 0) {
        process.stdout.write(`${changed.join(', ')} changed\n`);
      }
      print(report);
    },
    onError(error) {
      process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    },
  });
  process.stdout.write(`watching ${opts.src}\n`);

  const stop = () => {
    watcher.close();
    process.exitCode = 0;
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
    process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
