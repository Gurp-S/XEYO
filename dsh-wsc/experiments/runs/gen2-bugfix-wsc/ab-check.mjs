// Temporary A/B harness: baseline (pre-fix) implementation vs src/slug.js.
import { slugify as next } from './src/slug.js';

function baseline(input) {
  return String(input).toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
}

const corpus = [
  ['Hello World', 'hello-world'],
  ['Hello, World!', 'hello-world'],
  ['a   b', 'a-b'],
  ['--x--', 'x'],
  ['Über Café', 'uber-cafe'],
  ['A_B', 'a-b'],
  ['---', ''],
  ['   ', ''],
  ['', ''],
  ['  Trim Me  ', 'trim-me'],
  ['foo--bar', 'foo-bar'],
  ['Café  Ünïon -- 2024', 'cafe-union-2024'],
  ['straße', 'strasse'],
  ['Łódź', 'lodz'],
  ['naïve résumé', 'naive-resume'],
  ['Æther Œuvre', 'aether-oeuvre'],
  ['İstanbul', 'istanbul'],
  ['100% Done', '100-done'],
  ['a - b - c', 'a-b-c'],
  ['日本語', ''],
  ['snake_case_and-dash', 'snake-case-and-dash'],
  ['x.y/z', 'x-y-z'],
  ['V1.2.3', 'v1-2-3'],
  ['emoji 🚀 launch', 'emoji-launch'],
];

const rows = corpus.map(([input, expected]) => {
  const before = baseline(input);
  const after = next(input);
  const beforeOk = before === expected;
  const afterOk = after === expected;
  const mark = (ok) => (ok ? 'PASS' : 'FAIL');
  return {
    input: JSON.stringify(input),
    expected,
    before,
    after,
    beforeOk: mark(beforeOk),
    afterOk: mark(afterOk),
    changed: before === after ? '' : 'changed',
  };
});

console.table(rows);
const beforePass = rows.filter((r) => r.beforeOk === 'PASS').length;
const afterPass = rows.filter((r) => r.afterOk === 'PASS').length;
console.log(`baseline ${beforePass}/${rows.length}  fixed ${afterPass}/${rows.length}`);
const regressions = rows.filter((r) => r.beforeOk === 'PASS' && r.afterOk === 'FAIL');
console.log('regressions:', regressions.length === 0 ? 'none' : regressions);
