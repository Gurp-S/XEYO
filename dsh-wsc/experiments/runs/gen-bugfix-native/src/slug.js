// Latin letters that NFD does not decompose into a base letter plus a
// combining mark, so they need an explicit ASCII transliteration.
const LATIN_FALLBACKS = new Map([
  ['ß', 'ss'],
  ['æ', 'ae'],
  ['œ', 'oe'],
  ['ø', 'o'],
  ['đ', 'd'],
  ['ð', 'd'],
  ['þ', 'th'],
  ['ł', 'l'],
  ['ħ', 'h'],
  ['ı', 'i'],
  ['ŋ', 'n'],
  ['ŧ', 't'],
]);

const COMBINING_MARK = /\p{M}/gu;
const FALLBACK_LETTER = new RegExp(`[${[...LATIN_FALLBACKS.keys()].join('')}]`, 'g');
const NON_ALPHANUMERIC = /[^a-z0-9]+/g;
const EDGE_SEPARATOR = /^-+|-+$/g;

export function slugify(input) {
  return String(input)
    .toLowerCase()
    .normalize('NFD')
    .replace(COMBINING_MARK, '')
    .replace(FALLBACK_LETTER, (letter) => LATIN_FALLBACKS.get(letter))
    .replace(NON_ALPHANUMERIC, '-')
    .replace(EDGE_SEPARATOR, '');
}

export function slugifyAll(list) {
  return list.map((item) => slugify(item));
}
