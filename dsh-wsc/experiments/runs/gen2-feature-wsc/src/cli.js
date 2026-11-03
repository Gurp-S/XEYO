export const USAGE = 'usage: csv-lite <file>\n';

export function parseArgs(argv) {
  let file;
  let delimiter = ',';
  let header = true;
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--no-header') { header = false; continue; }
    if (arg === '--delimiter') {
      const value = argv[index + 1];
      if (value === undefined || value.length !== 1 || value.startsWith('--')) return null;
      delimiter = value;
      index += 1;
      continue;
    }
    if (file === undefined && !arg.startsWith('--')) { file = arg; continue; }
    return null;
  }
  if (file === undefined) return null;
  return { file, delimiter, header };
}

export function renderRows(rows, { header = true } = {}) {
  if (!header) return rows;
  const [names, ...body] = rows;
  if (names === undefined) return [];
  return body.map((cells) => Object.fromEntries(names.map((name, index) => [name, cells[index] ?? ''])));
}
