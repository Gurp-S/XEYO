/**
 * Split text into words.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function tokenize(text) {
  return text.split(/\s+/).filter((word) => word.length > 0);
}
