import { toAscii } from './transliterate.js';

export function slugify(input) {
  return toAscii(input)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function slugifyAll(list) {
  return list.map((item) => slugify(item));
}
