/**
 * Split gui/src/index.css into styles/* by manifest.
 * Does NOT modify index.css (fallback). Writes styles/entry.css as alternate entry.
 *
 * Usage:
 *   node scripts/split-index-css.cjs           # write files
 *   node scripts/split-index-css.cjs --dry     # plan + validate only
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const manifestPath = path.join(__dirname, 'split-index-css.manifest.json');
const dry = process.argv.includes('--dry');

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const sourcePath = path.join(root, manifest.source);
const raw = fs.readFileSync(sourcePath, 'utf8');
const nl = raw.includes('\r\n') ? '\r\n' : '\n';
const lines = raw.split(/\r?\n/);
const total = lines.length;

/** Normalize to ranges with concrete `to` (1-based inclusive). */
const slices = manifest.slices.map(s => ({
	...s,
	to: s.to == null ? total : s.to,
}));

function fail(msg) {
	console.error('FAIL:', msg);
	process.exit(1);
}

/* —— force-classify: every line 1..total must be owned exactly once —— */
const owner = new Array(total + 1).fill(null);
owner[1] = '__entry_import__'; // @import "tailwindcss" lives in entry only

for (const s of slices) {
	if (s.from < 1 || s.to > total || s.from > s.to) {
		fail(`bad range ${s.file}: ${s.from}-${s.to} (total ${total})`);
	}
	for (let i = s.from; i <= s.to; i++) {
		if (owner[i]) {
			fail(`overlap line ${i}: ${owner[i]} vs ${s.file}`);
		}
		owner[i] = s.file;
	}
}

const orphans = [];
for (let i = 1; i <= total; i++) {
	if (!owner[i]) orphans.push(i);
}
if (orphans.length) {
	fail(`unclassified lines (${orphans.length}): ${orphans.slice(0, 20).join(', ')}…`);
}

/* —— reconstruct body (lines 2..total) must match concat of slices —— */
const reconstructed = [];
for (const s of slices) {
	for (let i = s.from; i <= s.to; i++) {
		reconstructed.push(lines[i - 1]);
	}
}
const bodyOriginal = lines.slice(1).join('\n');
const bodyRebuilt = reconstructed.join('\n');
if (bodyOriginal !== bodyRebuilt) {
	fail('concatenation of slices !== source body (lines 2..end)');
}

console.log(`OK classify: ${total} lines, ${slices.length} slices, no orphans`);
for (const s of slices) {
	const n = s.to - s.from + 1;
	console.log(`  ${String(n).padStart(5)}  L${s.from}-${s.to}  ${s.file}  — ${s.desc}`);
}

if (dry) {
	console.log('dry-run: no files written; index.css untouched');
	process.exit(0);
}

const stylesDir = path.join(root, 'src/styles');
fs.mkdirSync(stylesDir, {recursive: true});

const banner = (desc, from, to) =>
	`/* auto-split from index.css L${from}-${to} — ${desc}; do not edit order relative to styles/entry.css */${nl}`;

for (const s of slices) {
	const abs = path.join(root, s.file);
	fs.mkdirSync(path.dirname(abs), {recursive: true});
	// Always terminate with nl after the last slice line (even if that line is blank),
	// so trailing empty lines inside a slice survive round-trip.
	const chunk = lines.slice(s.from - 1, s.to).join(nl) + nl;
	const out = banner(s.desc, s.from, s.to) + chunk;
	fs.writeFileSync(abs, out);
	console.log('wrote', s.file);
}

const entryPath = path.join(root, manifest.entry);
const importBlock = [
	'/* Alternate CSS entry: same cascade as index.css, split for maintainability.',
	' * Fallback: keep importing ../index.css from main.tsx until verified.',
	' * Switch: import "./styles/entry.css" instead of "./index.css".',
	' */',
	'@import "tailwindcss";',
	...slices.map(s => {
		const rel = path.posix.join(
			'.',
			path.relative(path.dirname(entryPath), path.join(root, s.file)).replace(/\\/g, '/'),
		);
		return `@import "${rel}";`;
	}),
	'',
].join(nl);

fs.writeFileSync(entryPath, importBlock);
console.log('wrote', manifest.entry);
console.log('index.css UNCHANGED (fallback). main.tsx still points at index.css.');
