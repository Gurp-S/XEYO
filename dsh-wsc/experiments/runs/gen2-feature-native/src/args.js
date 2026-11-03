export const USAGE = 'usage: csv-lite <file>\n';

const DELIMITER_FLAG = '--delimiter';
const DELIMITER_PREFIX = `${DELIMITER_FLAG}=`;

// Collects the CLI options independently of their position: recognised flags are
// removed wherever they appear and the first remaining token is the file.
export function parseCliArgs(argv) {
  const options = { file: undefined, delimiter: ',', header: true, errors: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--no-header') { options.header = false; continue; }
    if (arg === DELIMITER_FLAG) {
      const value = argv[index + 1];
      if (value === undefined) { options.errors.push(`${DELIMITER_FLAG} requires a value`); continue; }
      options.delimiter = value;
      index += 1;
      continue;
    }
    if (arg.startsWith(DELIMITER_PREFIX)) {
      options.delimiter = arg.slice(DELIMITER_PREFIX.length);
      continue;
    }
    if (options.file === undefined) options.file = arg;
  }
  if (options.errors.length === 0 && [...options.delimiter].length !== 1) {
    options.errors.push(`${DELIMITER_FLAG} expects a single character`);
  }
  return options;
}
