/**
 * Rasterize brand SVG → PNG → tauri icon set.
 * Usage: node scripts/gen-app-icon.mjs
 */
import {execSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Resvg} from '@resvg/resvg-js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const outPng = path.join(root, 'src-tauri', 'app-icon-source.png');
const whiteSvg = path.join(
	root,
	'..',
	'assets',
	'xeyo-icon-white.svg',
);

const mark = fs.readFileSync(whiteSvg, 'utf8');
const pathMatch = mark.match(/<path[^>]*d="([^"]+)"/);
if (!pathMatch) {
	throw new Error('path d not found in white svg');
}
const d = pathMatch[1];

const appSvg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <rect width="1024" height="1024" rx="192" fill="#12161c"/>
  <path fill="#FFFFFF" fill-rule="nonzero" d="${d}"/>
</svg>`;

const resvg = new Resvg(appSvg, {
	fitTo: {mode: 'width', value: 1024},
	background: 'transparent',
});
fs.writeFileSync(outPng, resvg.render().asPng());
console.log('wrote', outPng);

execSync(`npx tauri icon "${outPng}"`, {
	cwd: root,
	stdio: 'inherit',
	shell: true,
});
console.log('tauri icons regenerated');
