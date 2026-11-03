/**
 * Split text into words.
 *
 * A word is a run of `[a-z0-9']` after case folding, so apostrophes stay
 * inside the word (`don't`) while other punctuation is dropped.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text.toLowerCase().match(/[a-z0-9']+/g) ?? [];
}
