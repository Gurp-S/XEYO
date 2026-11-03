export const USAGE = 'usage: csv-lite [--delimiter <char>] [--no-header] <file>\n';

const DELIMITER_FLAG = '--delimiter';
const DELIMITER_PREFIX = `${DELIMITER_FLAG}=`;
const NO_HEADER_FLAG = '--no-header';
const RESERVED = new Set(['"', '\r', '\n']);

export class CliError extends Error {}

function toDelimiter(value) {
  if (typeof value !== 'string' || value.length !== 1) {
    throw new CliError(`${DELIMITER_FLAG} expects exactly one character`);
  }
  if (RESERVED.has(value)) {
    throw new CliError(`${DELIMITER_FLAG} cannot be ${JSON.stringify(value)}`);
  }
  return value;
}

export function parseArgs(argv) {
  const options = { delimiter: ',', header: true, file: undefined };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === NO_HEADER_FLAG) { options.header = false; continue; }
    if (arg === DELIMITER_FLAG) { options.delimiter = toDelimiter(argv[index + 1]); index += 1; continue; }
    if (arg.startsWith(DELIMITER_PREFIX)) { options.delimiter = toDelimiter(arg.slice(DELIMITER_PREFIX.length)); continue; }
    if (arg.startsWith('-') && arg !== '-') throw new CliError(`unknown option: ${arg}`);
    if (options.file === undefined) options.file = arg;
  }
  return options;
}
