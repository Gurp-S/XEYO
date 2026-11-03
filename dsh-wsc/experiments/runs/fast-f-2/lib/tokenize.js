/**
 * Split text into words.
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
