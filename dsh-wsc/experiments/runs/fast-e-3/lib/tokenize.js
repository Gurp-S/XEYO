/**
 * Split text into words.
 *
 * Only `[a-z0-9']` survives; every other character separates words, so an
 * apostrophe stays inside a word (`don't` is one word). Empty pieces are
 * dropped.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text
    .toLowerCase()
    .split(/[^a-z0-9']+/)
    .filter((word) => word.length > 0);
}
