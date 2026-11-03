/**
 * ASCII transliteration.
 *
 * Latin letters that Unicode can decompose (é, ü, ñ, ...) are handled by
 * NFKD + combining-mark stripping. Letters that do NOT decompose need an
 * explicit table. Everything else is left untouched for the caller to treat
 * as a separator.
 */

const SPECIAL_LATIN = new Map([
  ['ß', 'ss'],
  ['æ', 'ae'],
  ['œ', 'oe'],
  ['ø', 'o'],
  ['đ', 'd'],
  ['ð', 'd'],
  ['þ', 'th'],
  ['ł', 'l'],
  ['ı', 'i'],
  ['ħ', 'h'],
  ['ŧ', 't'],
  ['ŋ', 'n'],
]);

const SPECIAL_LATIN_PATTERN = new RegExp(
  `[${[...SPECIAL_LATIN.keys()].join('')}]`,
  'g',
);

/**
 * Fold a string down to ASCII letters and digits, dropping everything that
 * has no ASCII counterpart.
 *
 * @param {string} text
 * @returns {string}
 */
export function foldToAscii(text) {
  return String(text)
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')
    .replace(SPECIAL_LATIN_PATTERN, (char) => SPECIAL_LATIN.get(char));
}
