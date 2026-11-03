#!/usr/bin/env node
import path from 'node:path';
import { build, parseArgs, USAGE } from '../lib/build.js';
import { watchSources } from '../lib/watch.js';

function emit(opts, report) {
  if (opts.json) {
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

  const runOnce = async () => {
    try {
      emit(opts, await build(opts));
      return true;
    } catch (error) {
      process.stderr.write(
        `build failed: ${error instanceof Error ? error.message : String(error)}\n`,
      );
      return false;
    }
  };

  if (!opts.watch) return (await runOnce()) ? 0 : 1;

  const ok = await runOnce();
  if (!opts.watch) return ok ? 0 : 1;

  const srcDir = path.resolve(opts.src);
  const outDir = path.resolve(opts.out);
  const manifestPath = path.resolve(opts.manifest);
  const relativeOut = path.relative(srcDir, outDir).split(path.sep).join('/');
  const relativeManifest = path.relative(srcDir, manifestPath).split(path.sep).join('/');
  const ignore = (name) => {
    if (relativeOut && relativeOut !== '..' && !relativeOut.startsWith('../')) {
      if (name === relativeOut || name.startsWith(`${relativeOut}/`)) return true;
    }
    return relativeManifest !== '' && name === relativeManifest;
  };

  let running = false;
  let pending = false;
  let timer = null;
  const trigger = () => {
    if (running) {
      pending = true;
      return;
    }
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      timer = null;
      running = true;
      try {
        do {
          pending = false;
          await runOnce();
        } while (pending);
      } finally {
        running = false;
      }
    }, 0);
  };

  let watcher;
  try {
    watcher = watchSources(srcDir, trigger, {
      ignore,
      onError: (error) => {
        process.stderr.write(`watch error: ${error.message}\n`);
      },
    });
  } catch (error) {
    process.stderr.write(
      `watch unavailable: ${error instanceof Error ? error.message : String(error)}\n`,
    );
    return ok ? 0 : 1;
  }

  const stop = () => {
    if (timer) clearTimeout(timer);
    watcher.close();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
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
