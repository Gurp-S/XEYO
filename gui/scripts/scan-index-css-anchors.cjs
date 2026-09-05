/**
 * Scan index.css and print candidate section headers with line numbers.
 * Dry helper for building the split manifest.
 */
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '../src/index.css');
const lines = fs.readFileSync(file, 'utf8').split(/\r?\n/);

for (let i = 0; i < lines.length; i++) {
	const l = lines[i];
	const trimmed = l.trim();
	if (
		trimmed.startsWith('/* ===') ||
		trimmed.startsWith('/* ——') ||
		trimmed.startsWith('/* =====') ||
		/^\/\* [A-Z]/.test(trimmed) ||
		trimmed.includes('Motion system') ||
		trimmed.includes('Agent workflow') ||
		trimmed.includes('Composer /') ||
		trimmed.includes('Native sticky') ||
		trimmed.includes('Tauri') ||
		trimmed.includes('现代滚动条') ||
		trimmed.includes('Hover') ||
		trimmed.includes('Top fade') ||
		trimmed.includes('Geometry-only pin') ||
		trimmed.includes('User bubble') ||
		trimmed.includes('Code fence') ||
		trimmed.includes('Copilot-style') ||
		trimmed.includes('水墨') ||
		trimmed.includes('主题') ||
		trimmed.startsWith('@theme') ||
		trimmed.startsWith('@import') ||
		trimmed.startsWith(':root') ||
		/^html\[data-theme/.test(trimmed) ||
		trimmed.startsWith('.xy-menu-flyout') ||
		trimmed.startsWith('.xy-ctx-menu') ||
		trimmed.startsWith('.xy-sidebar ') ||
		trimmed.startsWith('.xy-composer-shell') ||
		trimmed.startsWith('.xy-turn-rail') ||
		trimmed.startsWith('.xy-usage')
	) {
		console.log(String(i + 1).padStart(5), trimmed.slice(0, 100));
	}
}
console.error('total lines', lines.length);
