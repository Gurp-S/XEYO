export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    outputs written in parallel (default: 4)
  --dry-run            report the plan without writing anything
  --watch              rebuild whenever a source file changes
  --json               print a machine-readable report
  --help, -h           show this help
`;

// A value that is not a positive safe integer is not clamped into range: a
// typo silently turned into "1" would look like a working build that is simply
// slower than asked for.
export function positiveInt(flag, raw) {
  const text = String(raw ?? '');
  if (!/^\d+$/.test(text)) throw new Error(`${flag} needs a positive integer, got ${JSON.stringify(raw)}`);
  const value = Number(text);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${flag} needs a positive integer, got ${JSON.stringify(raw)}`);
  }
  return value;
}

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: DEFAULT_CONCURRENCY,
    dryRun: false,
    watch: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => {
      const value = argv[(index += 1)];
      if (value === undefined) throw new Error(`${arg} needs a value`);
      return value;
    };
    if (arg === '--src') opts.src = next();
    else if (arg === '--out') opts.out = next();
    else if (arg === '--manifest') opts.manifest = next();
    else if (arg === '--concurrency') opts.concurrency = positiveInt(arg, next());
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  if (opts.watch && opts.dryRun) throw new Error('--watch cannot be combined with --dry-run');
  return opts;
}

export function formatReport(report) {
  const removed = report.removed.length + (report.removedOutputs?.length ?? 0);
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${removed} in ${report.durationMs}ms\n`;
}
