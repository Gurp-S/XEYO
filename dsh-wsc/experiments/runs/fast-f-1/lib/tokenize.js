/**
 * Split text into words.
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
