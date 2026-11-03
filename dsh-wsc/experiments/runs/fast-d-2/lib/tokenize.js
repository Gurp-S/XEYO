/**
 * Split text into words.
 *
 * Keeps only `[a-z0-9']`, lower-cased, so `Don't` becomes `don't`.
 * Apostrophes at the edges of a token are dropped; empty tokens are skipped.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  const words = [];
  for (const raw of String(text).toLowerCase().split(/[^a-z0-9']+/)) {
    const word = raw.replace(/^'+|'+$/g, '');
    if (word.length > 0) {
      words.push(word);
    }
  }
  return words;
}
