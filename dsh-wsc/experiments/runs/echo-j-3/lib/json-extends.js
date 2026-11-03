import { resolveDep } from './deps.js';

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function load(rel, readText, stack) {
  if (stack.includes(rel)) {
    throw new Error(`json extends cycle: ${[...stack, rel].join(' -> ')}`);
  }
  const value = JSON.parse(await readText(rel));
  if (!isPlainObject(value) || typeof value.extends !== 'string') {
    return { value, bases: [] };
  }
  const baseRel = resolveDep(rel, value.extends);
  const { extends: _dropped, ...own } = value;
  if (!baseRel) return { value: own, bases: [] };
  const base = await load(baseRel, readText, [...stack, rel]);
  if (!isPlainObject(base.value)) {
    throw new Error(`json extends base must be an object: ${rel} -> ${baseRel}`);
  }
  // The whole chain is a dependency: every layer's bytes reach the emitted file.
  return { value: { ...base.value, ...own }, bases: [baseRel, ...base.bases] };
}

export async function resolveJsonObject(rel, readText) {
  return load(rel, readText, []);
}
