/**
 * Split text into words.
 *
 * Only `[a-z0-9']` survives; an apostrophe belongs to the word. Everything
 * else acts as a separator, and empty strings are dropped.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9']+/g, ' ')
    .split(' ')
    .filter((word) => word.length > 0);
}
