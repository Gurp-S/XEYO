#!/usr/bin/env node
import path from 'node:path';
import { formatReport, parseArgs, USAGE } from '../lib/cli.js';
import { build } from '../lib/planner.js';
import { watch } from '../lib/watch.js';

const root = process.cwd();

function emit(report, json) {
  process.stdout.write(json ? `${JSON.stringify(report)}\n` : formatReport(report));
}

async function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n\n${USAGE}`);
    process.exitCode = 2;
    return;
  }
  if (opts.help) {
    process.stdout.write(USAGE);
    return;
  }
  try {
    emit(await build(opts, root), opts.json);
    if (!opts.watch) return;
    const stop = await watch({
      root: path.resolve(root, opts.src),
      onChange: async () => {
        try {
          emit(await build(opts, root), opts.json);
        } catch (error) {
          process.stderr.write(`build failed: ${error.message}\n`);
        }
      },
      onError: (error) => process.stderr.write(`watch failed: ${error.message}\n`),
    });
    const shutdown = () => {
      stop();
      process.exit(0);
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
  } catch (error) {
    process.stderr.write(`build failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}

main();
