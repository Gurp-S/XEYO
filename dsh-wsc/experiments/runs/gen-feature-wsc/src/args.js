export class UsageError extends Error {}

export function parseArgs(argv) {
  const options = { file: null, delimiter: ',', header: true };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--no-header') {
      options.header = false;
      continue;
    }
    if (arg === '--delimiter') {
      const value = argv[index + 1];
      if (value === undefined) throw new UsageError('--delimiter requires a value');
      options.delimiter = value;
      index += 1;
      continue;
    }
    if (arg.startsWith('--delimiter=')) {
      options.delimiter = arg.slice('--delimiter='.length);
      continue;
    }
    if (options.file === null) {
      options.file = arg;
      continue;
    }
    throw new UsageError(`unexpected argument: ${arg}`);
  }
  if (options.file === null) throw new UsageError('missing file argument');
  if ([...options.delimiter].length !== 1) {
    throw new UsageError('--delimiter must be a single character');
  }
  return options;
}
