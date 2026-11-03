#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { startWatch } from '../lib/watch.js';

function printReport(report, opts) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } else {
    process.stdout.write(
      `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
    );
  }
}

function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) {
    const close = await startWatch(opts, process.cwd(), {
      onReport: (report) => printReport(report, opts),
      onError: (error) => process.stderr.write(`build failed: ${errorText(error)}\n`),
    });
    process.stderr.write(`watching ${opts.src} for changes (press Ctrl-C to stop)\n`);
    const shutdown = async () => {
      await close();
      process.exit(0);
    };
    process.once('SIGINT', () => {
      void shutdown();
    });
    process.once('SIGTERM', () => {
      void shutdown();
    });
    // Watchers keep the process alive; this promise intentionally never settles.
    return new Promise(() => {});
  }
  const report = await build(opts);
  printReport(report, opts);
  return 0;
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    process.stderr.write(`build failed: ${errorText(error)}\n`);
    process.exitCode = 1;
  },
);
