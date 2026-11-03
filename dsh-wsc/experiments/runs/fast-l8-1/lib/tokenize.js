/**
 * Split text into words.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text.toLowerCase().match(/[a-z0-9']+/g) ?? [];
}
