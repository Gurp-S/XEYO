/**
 * Split text into words.
 *
 * A word is a run of `[a-z0-9']` after case folding; every other character
 * separates words. Apostrophes stay inside a word, so `Don't` is one word.
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
