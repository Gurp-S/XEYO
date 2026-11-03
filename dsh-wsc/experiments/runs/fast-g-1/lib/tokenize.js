/**
 * Split text into lowercase words.
 *
 * Only `[a-z0-9']` survives; every other character is a separator, and an
 * apostrophe is part of the word it sits in (`don't` is one word).
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text.toLowerCase().split(/[^a-z0-9']+/).filter((word) => word.length > 0);
}
