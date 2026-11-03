import { normaliseSettings } from './format.js';

export function loadSettings(raw) {
  return normaliseSettings(raw);
}
