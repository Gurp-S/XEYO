/**
 * Split an existing styles/*.css domain file into smaller files for maintainability.
 * Leaves a thin barrel (same path) that only @imports the children — entry.css unchanged.
 *
 * Usage (from gui/):
 *   node scripts/split-domain-css.cjs scripts/split-workflow-css.manifest.json
 *   node scripts/split-domain-css.cjs scripts/split-app-chrome-css.manifest.json
 *   node scripts/split-domain-css.cjs scripts/split-workflow-css.manifest.json --dry
 *
 * Safety:
 *   - force-classify: every body line owned exactly once
 *   - concat of children === source body (banner stripped)
 *   - refuses to overwrite children unless --force
 *   - with --force, backs up the original domain file to *.pre-split.bak
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const dry = process.argv.includes('--dry');
const force = process.argv.includes('--force');
const manifestArg = process.argv.find(
	(a, i) => i >= 2 && !a.startsWith('--'),
);

if (!manifestArg) {
	console.error(
		'Usage: node scripts/split-domain-css.cjs <manifest.json> [--dry] [--force]',
	);
	process.exit(1);
}

const manifestPath = path.isAbsolute(manifestArg)
	? manifestArg
	: path.join(root, manifestArg);
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

function fail(msg) {
	console.error('FAIL:', msg);
	process.exit(1);
}

const sourceAbs = path.join(root, manifest.source);
if (!fs.existsSync(sourceAbs)) fail(`missing source ${manifest.source}`);

const raw = fs.readFileSync(sourceAbs, 'utf8');
const nl = raw.includes('\r\n') ? '\r\n' : '\n';
const allLines = raw.split(/\r?\n/);

let bodyStart = 0;
if (
	allLines[0] &&
	/^\/\* auto-split from index\.css L\d+-\d+ —/.test(allLines[0])
) {
	bodyStart = 1;
}

const bodyLines = allLines.slice(bodyStart);
/* drop single trailing empty from final nl */
if (bodyLines.length && bodyLines[bodyLines.length - 1] === '') {
	bodyLines.pop();
}
const total = bodyLines.length;

const slices = manifest.slices.map(s => ({
	...s,
	to: s.to == null ? total : s.to,
}));

const owner = new Array(total + 1).fill(null);
for (const s of slices) {
	if (s.from < 1 || s.to > total || s.from > s.to) {
		fail(`bad range ${s.file}: ${s.from}-${s.to} (body total ${total})`);
	}
	for (let i = s.from; i <= s.to; i++) {
		if (owner[i]) fail(`overlap line ${i}: ${owner[i]} vs ${s.file}`);
		owner[i] = s.file;
	}
}
const orphans = [];
for (let i = 1; i <= total; i++) {
	if (!owner[i]) orphans.push(i);
}
if (orphans.length) {
	fail(
		`unclassified body lines (${orphans.length}): ${orphans
			.slice(0, 20)
			.join(', ')}…`,
	);
}

const rebuilt = [];
for (const s of slices) {
	for (let i = s.from; i <= s.to; i++) rebuilt.push(bodyLines[i - 1]);
}
if (rebuilt.join('\n') !== bodyLines.join('\n')) {
	fail('concatenation of slices !== source body');
}

console.log(
	`OK classify: ${manifest.source} body ${total} lines → ${slices.length} slices`,
);
for (const s of slices) {
	const n = s.to - s.from + 1;
	console.log(
		`  ${String(n).padStart(5)}  L${s.from}-${s.to}  ${s.file}  — ${s.desc}`,
	);
}

if (dry) {
	console.log('dry-run: no files written');
	process.exit(0);
}

for (const s of slices) {
	const abs = path.join(root, s.file);
	if (fs.existsSync(abs) && !force) {
		fail(`${s.file} exists; pass --force to overwrite`);
	}
}

const bak = `${sourceAbs}.pre-split.bak`;
if (!fs.existsSync(bak)) {
	fs.writeFileSync(bak, raw);
	console.log('backup', path.relative(root, bak));
} else {
	console.log('backup exists, skip rewrite:', path.relative(root, bak));
}

const banner = (desc, from, to) =>
	`/* auto-split from ${path.posix.join(
		...manifest.source.split(/[/\\]/),
	)} body L${from}-${to} — ${desc}; imported via barrel ${path.posix.join(
		...manifest.source.split(/[/\\]/),
	)} */${nl}`;

for (const s of slices) {
	const abs = path.join(root, s.file);
	fs.mkdirSync(path.dirname(abs), {recursive: true});
	const chunk = bodyLines.slice(s.from - 1, s.to).join(nl) + nl;
	fs.writeFileSync(abs, banner(s.desc, s.from, s.to) + chunk);
	console.log('wrote', s.file);
}

const barrelHeader = [
	`/* Domain barrel: was monolithic ${path.posix.join(
		...manifest.source.split(/[/\\]/),
	)}.`,
	` * Children below are a partition of the previous body; cascade order matters.`,
	` * Restore: copy ${path.basename(sourceAbs)}.pre-split.bak over this file.`,
	` */`,
	'',
];
const imports = slices.map(s => {
	const rel = path.posix.relative(
		path.posix.dirname(manifest.source.replace(/\\/g, '/')),
		s.file.replace(/\\/g, '/'),
	);
	return `@import "./${rel}";`;
});
fs.writeFileSync(sourceAbs, [...barrelHeader, ...imports, ''].join(nl));
console.log('rewrote barrel', manifest.source);
console.log('entry.css unchanged (still imports the barrel path).');
