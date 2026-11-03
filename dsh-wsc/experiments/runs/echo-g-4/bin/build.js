#!/usr/bin/env node
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchBuild } from '../lib/watch.js';

function format(report) {
  const parts = [
    `built ${report.built.length}`,
    `skipped ${report.skipped.length}`,
    `deleted ${report.deleted.length}`,
    `removed ${report.removed.length}`,
  ];
  if (report.manifest !== 'ok') parts.push(`manifest ${report.manifest}`);
  return `${parts.join(', ')} in ${report.durationMs}ms\n`;
}

function emit(opts, report, stream = process.stdout) {
  stream.write(opts.json ? `${JSON.stringify(report)}\n` : format(report));
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }

  if (opts.watch) {
    emit(opts, await build(opts));
    process.stdout.write('watching for changes\n');
    const stop = watchBuild(opts, {
      onReport: (report) => emit(opts, report),
      onError: (error) => process.stderr.write(`build failed: ${error.message}\n`),
    });
    const shutdown = () => {
      stop();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
    return null;
  }

  emit(opts, await build(opts));
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
