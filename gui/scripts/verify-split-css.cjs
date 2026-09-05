/**
 * Verify split styles/* ≡ index.css (source + Vite-compiled).
 *
 * Usage (from gui/):
 *   node scripts/verify-split-css.cjs
 *   node scripts/verify-split-css.cjs --source-only
 *
 * Exit 0 = OK. Exit 1 = mismatch / build error.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const root = path.join(__dirname, '..');
const manifest = JSON.parse(
	fs.readFileSync(path.join(__dirname, 'split-index-css.manifest.json'), 'utf8'),
);
const sourceOnly = process.argv.includes('--source-only');

function sha(s) {
	return crypto.createHash('sha256').update(s).digest('hex').slice(0, 16);
}

function fail(msg) {
	console.error('FAIL:', msg);
	process.exit(1);
}

function ok(msg) {
	console.log('OK:', msg);
}

function stripTrailingEmpty(lines) {
	if (lines.length && lines[lines.length - 1] === '') lines.pop();
	return lines;
}

function stripAutoSplitBanner(lines) {
	if (
		lines[0] &&
		(/^\/\* auto-split from index\.css L\d+-\d+ —/.test(lines[0]) ||
			/^\/\* auto-split from .+ body L\d+-\d+ —/.test(lines[0]))
	) {
		lines.shift();
	}
	return lines;
}

function isDomainBarrel(lines) {
	const meaningful = lines.filter(l => l.trim().length > 0);
	if (meaningful.length === 0) return false;
	if (meaningful.some(l => l.includes('Domain barrel'))) return true;
	return meaningful.every(l => {
		const t = l.trim();
		return (
			t.startsWith('/*') ||
			t.startsWith('*') ||
			t.startsWith('*/') ||
			t.startsWith('@import ')
		);
	});
}

function readSliceBody(file) {
	const abs = path.join(root, file);
	if (!fs.existsSync(abs)) fail(`missing ${file}`);
	let lines = fs.readFileSync(abs, 'utf8').split(/\r?\n/);
	lines = stripAutoSplitBanner(lines);
	lines = stripTrailingEmpty(lines);

	/* Domain barrel (workflow.css / app-chrome.css after further split) */
	if (isDomainBarrel(lines)) {
		const dir = path.dirname(abs);
		const out = [];
		for (const line of lines) {
			const m = line.match(/^@import\s+"(\.\/[^"]+)";\s*$/);
			if (!m) continue;
			const childAbs = path.join(dir, m[1]);
			const rel = path.relative(root, childAbs).replace(/\\/g, '/');
			let child = fs.readFileSync(childAbs, 'utf8').split(/\r?\n/);
			child = stripAutoSplitBanner(child);
			child = stripTrailingEmpty(child);
			out.push(...child);
		}
		return out;
	}
	return lines;
}

/* —— Layer 1: each slice file ≡ index.css[from..to] —— */
const indexRaw = fs.readFileSync(path.join(root, manifest.source), 'utf8');
const indexLines = indexRaw.split(/\r?\n/);
const total = indexLines.length;
const slices = manifest.slices.map((s) => ({
	...s,
	to: s.to == null ? total : s.to,
}));

const rebuilt = [];
const expectedAll = [];
for (const s of slices) {
	const got = readSliceBody(s.file);
	const bakAbs = path.join(root, `${s.file}.pre-split.bak`);
	let expected;
	if (fs.existsSync(bakAbs)) {
		/* Domain further-split: truth is pre-split.bak, not the older index.css range */
		let bakLines = fs.readFileSync(bakAbs, 'utf8').split(/\r?\n/);
		bakLines = stripAutoSplitBanner(bakLines);
		bakLines = stripTrailingEmpty(bakLines);
		expected = bakLines;
	} else {
		expected = indexLines.slice(s.from - 1, s.to);
	}
	if (got.join('\n') !== expected.join('\n')) {
		fail(
			`${s.file} ≠ ${fs.existsSync(bakAbs) ? 'pre-split.bak' : `index.css L${s.from}-${s.to}`}\n` +
				`  expected ${expected.length} lines sha=${sha(expected.join('\n'))}\n` +
				`  got      ${got.length} lines sha=${sha(got.join('\n'))}`,
		);
	}
	rebuilt.push(...got);
	expectedAll.push(...expected);
}

const rebuiltBody = rebuilt.join('\n').replace(/\n+$/, '');
const expectedBody = expectedAll.join('\n').replace(/\n+$/, '');
if (rebuiltBody !== expectedBody) {
	fail('concat of slices ≠ expected body (index + domain bak)');
}
ok(
	`source slices match (${sha(rebuiltBody)}, ${slices.length} files; domain bak used where present)`,
);

if (sourceOnly) {
	console.log('source-only: skip Vite compile compare');
	process.exit(0);
}

/* —— Layer 2: Vite+Tailwind compiled CSS —— */
async function compileCss(relPath) {
	const {createServer} = await import('vite');
	const server = await createServer({
		root,
		configFile: path.join(root, 'vite.config.ts'),
		server: {middlewareMode: true},
		appType: 'custom',
	});
	try {
		const url = '/' + relPath.replace(/\\/g, '/');
		const result = await server.transformRequest(url, {ssr: false});
		if (!result || typeof result.code !== 'string') {
			fail(`Vite transform returned empty for ${url}`);
		}
		return result.code;
	} finally {
		await server.close();
	}
}

/** Pull the real CSS string out of Vite's HMR JS wrapper. */
function extractViteCss(moduleCode) {
	const m = moduleCode.match(/const __vite__css = ("(?:\\.|[^"\\])*")/);
	if (!m) fail('could not find const __vite__css = "..." in Vite transform output');
	return JSON.parse(m[1]);
}

function normalizeCss(css) {
	return css
		.replace(/\r\n/g, '\n')
		// auto-split banners + entry header comments are not in index.css
		.replace(/\/\* auto-split from index\.css[\s\S]*?\*\//g, '')
		.replace(/\/\* Alternate CSS entry:[\s\S]*?\*\//g, '')
		.replace(/\/\*# sourceMappingURL=.*?\*\//g, '')
		.replace(/\n{3,}/g, '\n\n')
		.trim();
}

(async () => {
	console.log('compiling index.css …');
	const a = normalizeCss(extractViteCss(await compileCss('src/index.css')));
	console.log('compiling styles/entry.css …');
	const b = normalizeCss(extractViteCss(await compileCss('src/styles/entry.css')));

	const ha = sha(a);
	const hb = sha(b);
	console.log(`  index.css      CSS sha=${ha} len=${a.length}`);
	console.log(`  styles/entry   CSS sha=${hb} len=${b.length}`);

	if (a === b) {
		ok('Vite-compiled CSS payload is byte-identical');
		console.log(
			'\nVerdict: split ≡ index.css (source + compiled). Safe to switch main.tsx when ready.',
		);
		process.exit(0);
	}

	let i = 0;
	while (i < a.length && i < b.length && a[i] === b[i]) i++;
	const win = (s, at) => s.slice(Math.max(0, at - 60), at + 80).replace(/\n/g, '\\n');
	console.error('FAIL: compiled CSS payload differs');
	console.error(`  first diff @ char ${i}`);
	console.error(`  index: …${win(a, i)}…`);
	console.error(`  entry: …${win(b, i)}…`);
	// Optional dump for manual diff
	const dumpDir = path.join(root, 'scripts/.css-verify');
	fs.mkdirSync(dumpDir, {recursive: true});
	fs.writeFileSync(path.join(dumpDir, 'from-index.css'), a);
	fs.writeFileSync(path.join(dumpDir, 'from-entry.css'), b);
	console.error(`  dumped: scripts/.css-verify/from-index.css & from-entry.css`);
	console.error('\nVerdict: do NOT switch main.tsx yet — investigate above.');
	process.exit(1);
})().catch((err) => {
	console.error('FAIL: Vite compile', err);
	process.exit(1);
});
