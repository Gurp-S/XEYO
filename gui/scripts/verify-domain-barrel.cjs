/**
 * Quick check: domain barrel @imports expand to pre-split.bak body.
 * Usage: node scripts/verify-domain-barrel.cjs
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const names = ['workflow', 'app-chrome'];

function strip(lines) {
	if (lines[0] && /^\/\* auto-split from /.test(lines[0])) lines.shift();
	if (lines.length && lines[lines.length - 1] === '') lines.pop();
	return lines;
}

let failed = false;
for (const name of names) {
	const barrel = path.join(root, `src/styles/${name}.css`);
	const bak = path.join(root, `src/styles/${name}.css.pre-split.bak`);
	if (!fs.existsSync(barrel) || !fs.existsSync(bak)) {
		console.error('FAIL: missing', name);
		failed = true;
		continue;
	}
	const dir = path.dirname(barrel);
	const out = [];
	for (const line of fs.readFileSync(barrel, 'utf8').split(/\r?\n/)) {
		const m = line.match(/^@import\s+"(\.\/[^"]+)";\s*$/);
		if (!m) continue;
		let child = fs
			.readFileSync(path.join(dir, m[1]), 'utf8')
			.split(/\r?\n/);
		child = strip(child);
		out.push(...child);
	}
	let expected = fs.readFileSync(bak, 'utf8').split(/\r?\n/);
	expected = strip(expected);
	if (out.join('\n') !== expected.join('\n')) {
		console.error(
			`FAIL: ${name} barrel ≠ bak (${out.length} vs ${expected.length})`,
		);
		failed = true;
	} else {
		console.log(`OK: ${name} barrel ≡ bak (${out.length} lines)`);
	}
}
process.exit(failed ? 1 : 0);
