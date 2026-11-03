/**
 * Split text into lowercase words.
 *
 * Only `[a-z0-9']` is kept; everything else is a separator. An apostrophe is
 * part of a word (`don't` is one word). Empty strings are never returned.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  if (typeof text !== 'string') {
    return [];
  }
  return text.toLowerCase().match(/[a-z0-9']+/g) ?? [];
}
