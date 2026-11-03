#!/usr/bin/env node
import path from 'node:path';
import { build, parseArgs, USAGE } from '../lib/build.js';
import { createTreeWatcher } from '../lib/watch.js';

function print(report, opts) {
  if (opts.json) {
    process.stdout.write(`${JSON.stringify(report)}\n`);
    return;
  }
  process.stdout.write(
    `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
  );
}

// Watch mode builds once, then rebuilds on every settled change. A failed
// rebuild keeps the previous output and the watcher alive: a half-written
// source file is a transient state, not a reason to stop watching.
async function watch(opts) {
  const rebuild = async () => {
    try {
      print(await build(opts), opts);
    } catch (error) {
      process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    }
  };
  await rebuild();
  const watcher = await createTreeWatcher(path.resolve(process.cwd(), opts.src), rebuild);
  await watcher.start();
  await new Promise((resolve) => {
    process.once('SIGINT', resolve);
    process.once('SIGTERM', resolve);
  });
  watcher.close();
  return 0;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(USAGE);
    return 0;
  }
  if (opts.watch) return watch(opts);
  print(await build(opts), opts);
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
