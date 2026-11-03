// Letters that carry no canonical (NFD) decomposition but do have a common
// ASCII spelling. Keys are lowercase because transliteration runs after
// lowercasing.
const LATIN_FALLBACK = new Map([
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
  ['ŋ', 'n'],
  ['ŧ', 't'],
]);

// Folds accented and non-ASCII Latin letters onto their ASCII base letter, so
// they transliterate instead of being dropped as symbols.
function toAscii(text) {
  const stripped = text.normalize('NFD').replace(/\p{M}+/gu, '');
  let out = '';
  for (const char of stripped) {
    out += LATIN_FALLBACK.get(char) ?? char;
  }
  return out;
}

export function slugify(input) {
  return toAscii(String(input).toLowerCase())
    // Any run of non-alphanumerics is one word boundary, so spaces, dashes,
    // underscores and punctuation all collapse into a single dash.
    .replace(/[^a-z0-9]+/g, '-')
    // Leading/trailing boundaries are not words.
    .replace(/^-+|-+$/g, '');
}

export function slugifyAll(list) {
  return list.map((item) => slugify(item));
}
