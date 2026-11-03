import { DEFAULT_SRC, DEFAULT_OUT, DEFAULT_MANIFEST, defaultConcurrency } from './engine.js';

export { DEFAULT_SRC, DEFAULT_OUT, DEFAULT_MANIFEST };
export { planBuild, build } from './engine.js';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    files built at once (default: ${defaultConcurrency()})
  --watch              rebuild when the source directory changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: defaultConcurrency(),
    watch: false,
    dryRun: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') {
      const raw = argv[(index += 1)];
      const value = Number(raw);
      if (!Number.isInteger(value) || value < 1) throw new Error(`--concurrency needs a positive integer, got: ${raw}`);
      opts.concurrency = value;
    } else if (arg === '--watch') opts.watch = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}
