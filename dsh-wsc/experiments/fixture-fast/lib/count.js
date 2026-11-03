import { tokenize } from './tokenize.js';

/**
 * Count every word in the text.
 *
 * @param {string} text
 * @returns {Map<string, number>}
 */
export function count(text) {
  const counts = new Map();
  for (const word of tokenize(text)) {
    counts.set(word, (counts.get(word) ?? 0) + 1);
  }
  return counts;
}

/**
 * The most frequent words.
 *
 * @param {Map<string, number>} counts
 * @param {number} [limit]
 * @returns {Array<[string, number]>}
 */
export function top(counts, limit = 3) {
  return [...counts.entries()].sort((left, right) => right[1] - left[1]).slice(0, limit);
}
