// Unicode -> ASCII folding for slug input.
//
// Decomposable accented letters (é, ü, ñ, å …) are handled by NFKD + stripping
// the combining marks. The table below covers the Latin letters that have no
// canonical decomposition and would otherwise be dropped.
const FALLBACKS = new Map([
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
  ['ĸ', 'k'],
]);

// Every non-ASCII character becomes its ASCII spelling, or nothing at all.
export function toAscii(input) {
  const decomposed = String(input)
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '');
  let out = '';
  for (const char of decomposed) {
    if (char.charCodeAt(0) < 0x80) {
      out += char;
      continue;
    }
    const mapped = FALLBACKS.get(char.toLowerCase());
    if (mapped !== undefined) out += mapped;
  }
  return out;
}
