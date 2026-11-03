import { foldToAscii } from './transliterate.js';

export function slugify(input) {
  return foldToAscii(String(input).toLowerCase())
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export function slugifyAll(list) {
  return list.map((item) => slugify(item));
}
