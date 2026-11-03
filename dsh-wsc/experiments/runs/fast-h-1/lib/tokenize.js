/**
 * Split text into lowercase words.
 *
 * Only `[a-z0-9']` is kept, an apostrophe stays inside the word (`don't`),
 * every other punctuation is dropped and empty matches are never returned.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text.toLowerCase().match(/[a-z0-9']+/g) ?? [];
}
