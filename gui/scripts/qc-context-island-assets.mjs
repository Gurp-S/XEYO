import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const root = path.resolve('public/context-island');
const expected = [
  'island.svg', 'palm-tree.svg', 'coconut.svg',
  'sea/wave-01.svg', 'sea/wave-02.svg', 'sea/wave-03.svg', 'sea/wave-04.svg',
  'foam/foam-01.svg', 'foam/foam-02.svg',
  'stars/star-medium.svg', 'stars/star-small.svg', 'stars/sparkle.svg', 'stars/star-dot.svg',
  'character/character.svg',
  'emotion/dots.svg', 'emotion/exclamation.svg', 'emotion/question.svg', 'emotion/heart.svg', 'emotion/sleep.svg',
];
const errors = [];
const report = [];
for (const relative of expected) {
  const file = path.join(root, relative);
  if (!fs.existsSync(file)) {
    errors.push(`${relative}: missing`);
    continue;
  }
  const text = fs.readFileSync(file, 'utf8');
  if (!/<svg\b/i.test(text)) errors.push(`${relative}: missing svg root`);
  if (!/\bviewBox\s*=\s*["'][^"']+["']/i.test(text)) errors.push(`${relative}: missing viewBox`);
  if (/<image\b/i.test(text)) errors.push(`${relative}: embedded image element`);
  if (/<rect\b[^>]*\b(?:fill|style)\s*=\s*["'][^"']*(?:white|#fff|#ffffff)[^"']*["']/i.test(text)) errors.push(`${relative}: white background rect`);
  const hash = crypto.createHash('sha256').update(text).digest('hex');
  report.push({file: relative, bytes: Buffer.byteLength(text), sha256: hash});
}
const character = path.join(root, 'character/character.svg');
if (fs.existsSync(character)) {
  const text = fs.readFileSync(character, 'utf8');
  if (text.includes('mouth-added') || text.includes('mouth')) errors.push('character.svg: unexpected mouth marker');
}
console.log(JSON.stringify({count: report.length, errors, report}, null, 2));
if (errors.length) process.exit(1);
