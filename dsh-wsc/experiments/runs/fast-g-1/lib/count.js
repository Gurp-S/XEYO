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

function compareWords(left, right) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

/**
 * The most frequent words: count descending, then word ascending on ties.
 *
 * @param {Map<string, number>} counts
 * @param {number} [limit]
 * @returns {Array<[string, number]>}
 */
export function top(counts, limit = 3) {
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || compareWords(left[0], right[0]))
    .slice(0, limit);
}
