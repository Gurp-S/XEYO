/**
 * Dismantle scheduler — Phase A: extract chatStore pre-create helpers.
 *
 * Rules:
 * - Do NOT hand-edit business code; only run this script.
 * - Backup live file first; live untouched until verify passes.
 * - Helpers body = original lines 144–1522 with ONLY the documented mutable rewrite.
 * - Facade create() body = original lines 1524–EOF with ONLY the same rewrite.
 * - Round-trip verify: undo rewrite → must equal original mid-file bytes.
 * - On test/typecheck failure after apply → automatic rollback.
 *
 * Usage (from gui/):
 *   node scripts/dismantle-chatstore-phase-a.cjs backup|stage|verify|apply|test|rollback|run
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {spawnSync} = require('child_process');

const root = path.join(__dirname, '..');
const manifest = JSON.parse(
	fs.readFileSync(
		path.join(__dirname, 'dismantle-chatstore-phase-a.manifest.json'),
		'utf8',
	),
);
const cmd = process.argv[2] || 'help';

function fail(msg) {
	console.error('FAIL:', msg);
	process.exit(1);
}
function ok(msg) {
	console.log('OK:', msg);
}
function sha16(s) {
	return crypto.createHash('sha256').update(s).digest('hex').slice(0, 16);
}
function abs(rel) {
	return path.join(root, rel);
}
function readText(rel) {
	return fs.readFileSync(abs(rel), 'utf8');
}
function writeText(rel, body) {
	const p = abs(rel);
	fs.mkdirSync(path.dirname(p), {recursive: true});
	fs.writeFileSync(p, body);
}
function splitLines(raw) {
	const nl = raw.includes('\r\n') ? '\r\n' : '\n';
	return {nl, lines: raw.split(/\r?\n/)};
}
function sliceLines(lines, from, toInclusive) {
	return lines.slice(from - 1, toInclusive);
}
function metaPath() {
	return abs(path.join(manifest.backupDir, 'PHASE_A_META.json'));
}
function loadMeta() {
	if (!fs.existsSync(metaPath())) fail('missing PHASE_A_META.json — run backup');
	return JSON.parse(fs.readFileSync(metaPath(), 'utf8'));
}
function saveMeta(meta) {
	writeText(
		path.join(manifest.backupDir, 'PHASE_A_META.json'),
		JSON.stringify(meta, null, 2) + '\n',
	);
}

function applyIdRewrite(text, direction) {
	let out = text;
	for (const r of manifest.mutableRewrite) {
		if (direction === 'forward') {
			const re = new RegExp(`\\b${r.fromId}\\b`, 'g');
			out = out.replace(re, r.toId);
		} else {
			// toId may contain dots (selectSeqBox.value) — escape and match literally
			const escaped = r.toId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
			const re = new RegExp(escaped, 'g');
			out = out.replace(re, r.fromId);
		}
	}
	return out;
}

function rewriteDeclLine(line, direction) {
	for (const r of manifest.mutableRewrite) {
		if (direction === 'forward' && line.trim() === r.fromDecl) return r.toDecl;
		if (direction === 'back' && line.trim() === r.toDecl) return r.fromDecl;
	}
	return line;
}

function scrapeExportableNames(helperLines) {
	/** @type {Set<string>} */
	const values = new Set();
	/** @type {Set<string>} */
	const types = new Set();
	for (const line of helperLines) {
		let m;
		if ((m = line.match(/^export type (\w+)/))) types.add(m[1]);
		else if ((m = line.match(/^type (\w+)/))) types.add(m[1]);
		else if ((m = line.match(/^export const (\w+)/))) values.add(m[1]);
		else if ((m = line.match(/^export function (\w+)/))) values.add(m[1]);
		else if ((m = line.match(/^export async function (\w+)/))) values.add(m[1]);
		else if ((m = line.match(/^(?:async )?function (\w+)/))) values.add(m[1]);
		else if ((m = line.match(/^const (\w+)/))) values.add(m[1]);
		else if ((m = line.match(/^let (\w+)/))) values.add(m[1]);
	}
	// after forward decl rewrite, remoteMirror replaces let remoteMirrorTargetSid
	for (const r of manifest.mutableRewrite) {
		if (r.importAs) {
			values.delete(r.fromId);
			values.add(r.importAs);
		}
	}
	return {values, types};
}

function namesUsedIn(text, names) {
	const used = [];
	for (const name of names) {
		if (name.length < 2) continue;
		if (new RegExp(`\\b${name}\\b`).test(text)) used.push(name);
	}
	return used;
}

function parseImportBlocks(importLines) {
	const blocks = [];
	let cur = [];
	for (const line of importLines) {
		cur.push(line);
		if (/;/.test(line)) {
			blocks.push(cur);
			cur = [];
		}
	}
	if (cur.length) blocks.push(cur);
	return blocks;
}

/** Return binding names introduced by an import block (local names). */
function importLocalNames(blockLines) {
	const text = blockLines.join('\n');
	const names = new Set();
	let m = text.match(/^import\s+(\w+)\s+from\s+/m);
	if (m) names.add(m[1]);
	m = text.match(/^import\s+\*\s+as\s+(\w+)\s+from\s+/m);
	if (m) names.add(m[1]);
	const brace = text.match(/\{([\s\S]*?)\}/);
	if (brace) {
		for (const part of brace[1].split(',')) {
			const p = part.trim();
			if (!p) continue;
			const as = p.match(/^(?:type\s+)?(\w+)\s+as\s+(\w+)$/);
			if (as) {
				names.add(as[2]);
				continue;
			}
			const plain = p.match(/^(?:type\s+)?(\w+)$/);
			if (plain) names.add(plain[1]);
		}
	}
	return [...names];
}

/** Keep only used bindings inside an import block; drop block if none remain. */
function trimImportBlock(blockLines, usedText, nl) {
	const text = blockLines.join(nl);
	const fromMatch = text.match(/\bfrom\s+(['"][^'"]+['"])\s*;?\s*$/m);
	if (!fromMatch) return blockLines.some(l => new RegExp(`\\b\\w+\\b`).test(usedText)) ? blockLines : null;

	const from = fromMatch[1];
	// default / namespace imports
	let m = text.match(/^import\s+(\w+)\s+from\s+/m);
	if (m && !/\{/.test(text)) {
		return new RegExp(`\\b${m[1]}\\b`).test(usedText) ? blockLines : null;
	}
	m = text.match(/^import\s+\*\s+as\s+(\w+)\s+from\s+/m);
	if (m) {
		return new RegExp(`\\b${m[1]}\\b`).test(usedText) ? blockLines : null;
	}

	const brace = text.match(/\{([\s\S]*?)\}/);
	if (!brace) return null;

	const isTypeImport = /^import\s+type\s+\{/m.test(text);
	const kept = [];
	for (const part of brace[1].split(',')) {
		const raw = part.trim();
		if (!raw) continue;
		const as = raw.match(/^(type\s+)?(\w+)\s+as\s+(\w+)$/);
		if (as) {
			const local = as[3];
			if (new RegExp(`\\b${local}\\b`).test(usedText)) kept.push(raw);
			continue;
		}
		const plain = raw.match(/^(type\s+)?(\w+)$/);
		if (plain) {
			const local = plain[2];
			if (new RegExp(`\\b${local}\\b`).test(usedText)) kept.push(raw);
		}
	}
	if (!kept.length) return null;

	const head = isTypeImport ? 'import type' : 'import';
	// Prefer single-line when small
	if (kept.length <= 3 && kept.join(', ').length < 80) {
		return [`${head} {${kept.join(', ')}} from ${from};`];
	}
	return [
		`${head} {`,
		...kept.map((k, i) => `\t${k}${i < kept.length - 1 ? ',' : ''}`),
		`} from ${from};`,
	];
}

function filterImportBlocks(importLines, usedText, nl) {
	const kept = [];
	for (const block of parseImportBlocks(importLines)) {
		const trimmed = trimImportBlock(block, usedText, nl);
		if (trimmed && trimmed.length) kept.push(...trimmed);
	}
	return kept;
}

function buildHelpers(importLines, helperLines, nl) {
	const bodyLines = helperLines.map(l => rewriteDeclLine(l, 'forward'));
	let body = bodyLines.join(nl);
	body = applyIdRewrite(body, 'forward');
	if (!body.endsWith(nl)) body += nl;

	const scraped = scrapeExportableNames(body.split(/\r?\n/));
	const alreadyExported = new Set();
	for (const line of body.split(/\r?\n/)) {
		let m;
		if ((m = line.match(/^export (?:async )?function (\w+)/)))
			alreadyExported.add(m[1]);
		if ((m = line.match(/^export const (\w+)/))) alreadyExported.add(m[1]);
		if ((m = line.match(/^export let (\w+)/))) alreadyExported.add(m[1]);
		if ((m = line.match(/^export type (\w+)/))) alreadyExported.add(m[1]);
	}
	const needValueExport = [...scraped.values]
		.filter(n => !alreadyExported.has(n))
		.sort();
	const needTypeExport = [...scraped.types]
		.filter(n => !alreadyExported.has(n))
		.sort();

	const exportBlock = [];
	if (needValueExport.length) {
		exportBlock.push(`export {${needValueExport.join(', ')}};`);
	}
	if (needTypeExport.length) {
		exportBlock.push(`export type {${needTypeExport.join(', ')}};`);
	}

	const trimmedImports = filterImportBlocks(importLines, body, nl);
	const banner = [
		'/**',
		' * AUTO-EXTRACTED by dismantle-chatstore-phase-a.cjs (Phase A).',
		' * Body bytes ≡ chatStore.ts L144–1522 except documented mutable rewrite.',
		' * Do not hand-edit; re-run the scheduler script.',
		' */',
		'',
	].join(nl);

	return (
		banner +
		trimmedImports.join(nl) +
		(trimmedImports.length ? nl + nl : nl) +
		body +
		(exportBlock.length ? exportBlock.join(nl) + nl : '')
	);
}

function buildFacade(importLines, createLines, usedValues, usedTypes, nl) {
	let createBody = createLines.join(nl);
	createBody = applyIdRewrite(createBody, 'forward');
	if (!createBody.endsWith(nl)) createBody += nl;

	const publicTypes = manifest.publicReexports.types;
	const publicValues = manifest.publicReexports.values;

	const typeSet = new Set([...usedTypes, 'ChatState']);
	// public types are re-exported via `export type {…} from` — do not import unless create uses them
	for (const t of publicTypes) {
		if (new RegExp(`\\b${t}\\b`).test(createBody)) typeSet.add(t);
	}

	const valueSet = new Set([...usedValues]);
	for (const r of manifest.mutableRewrite) {
		if (r.importAs) valueSet.add(r.importAs);
	}
	for (const v of publicValues) {
		if (new RegExp(`\\b${v}\\b`).test(createBody)) valueSet.add(v);
	}
	for (const t of typeSet) valueSet.delete(t);

	const helperImportText = `${[...typeSet].join(' ')} ${[...valueSet].join(' ')} ${createBody}`;
	const trimmedImports = filterImportBlocks(importLines, helperImportText, nl);

	const banner = [
		'/**',
		' * AUTO-REWRITTEN facade by dismantle-chatstore-phase-a.cjs (Phase A).',
		' * create() body ≡ original L1524–EOF except documented mutable rewrite.',
		' */',
		'',
	].join(nl);

	const typeList = [...typeSet].sort().join(', ');
	const valueList = [...valueSet].sort().join(',\n\t');

	const helperImports = [];
	if (typeList) helperImports.push(`import type {${typeList}} from './chat/preStoreHelpers';`);
	if (valueList) helperImports.push(`import {\n\t${valueList},\n} from './chat/preStoreHelpers';`);

	return (
		banner +
		trimmedImports.join(nl) +
		nl +
		nl +
		helperImports.join(nl) +
		nl +
		nl +
		`export type {${publicTypes.join(', ')}} from './chat/preStoreHelpers';` +
		nl +
		`export {${publicValues.join(', ')}} from './chat/preStoreHelpers';` +
		nl +
		nl +
		createBody
	);
}

function backup() {
	// drop stale in-src staging from older script versions (would break tsc)
	const stale = abs('src/stores/chat/_staging');
	if (fs.existsSync(stale)) {
		fs.rmSync(stale, {recursive: true, force: true});
		ok('removed stale src/stores/chat/_staging');
	}
	const raw = readText(manifest.source);
	const ts = new Date().toISOString().replace(/[:.]/g, '-');
	const dest = path.join(manifest.backupDir, `chatStore.ts.${ts}`);
	writeText(dest, raw);
	saveMeta({
		phase: 'A',
		backedUpAt: new Date().toISOString(),
		backupFile: dest,
		originalSha: sha16(raw),
		source: manifest.source,
		applied: false,
	});
	ok(`backup → ${dest}`);
	ok(`sha ${sha16(raw)}`);
}

function stage() {
	const raw = readText(manifest.source);
	const {nl, lines} = splitLines(raw);
	const total = lines.length;
	const hr = manifest.helpersRange;
	const cr = manifest.createRange;
	const ir = manifest.importsRange;
	const createTo = cr.to == null ? total : cr.to;

	const importLines = sliceLines(lines, ir.from, ir.to);
	const helperLines = sliceLines(lines, hr.from, hr.to);
	const createLines = sliceLines(lines, cr.from, createTo);

	const createText = applyIdRewrite(createLines.join('\n'), 'forward');
	const scraped = scrapeExportableNames(
		helperLines.map(l => rewriteDeclLine(l, 'forward')),
	);
	const usedValues = namesUsedIn(createText, scraped.values);
	const usedTypes = namesUsedIn(createText, scraped.types);
	if (!usedTypes.includes('ChatState')) usedTypes.push('ChatState');

	const helpersSrc = buildHelpers(importLines, helperLines, nl);
	const facadeSrc = buildFacade(
		importLines,
		createLines,
		usedValues,
		usedTypes,
		nl,
	);

	const stageHelpers = path.join(manifest.stagingDir, 'preStoreHelpers.ts');
	const stageFacade = path.join(manifest.stagingDir, 'chatStore.ts');
	writeText(stageHelpers, helpersSrc);
	writeText(stageFacade, facadeSrc);

	// Sidecar: exact original mid for verify
	const gap = sliceLines(lines, hr.to + 1, cr.from - 1);
	const originalMid = [...helperLines, ...gap, ...createLines].join(nl);
	writeText(path.join(manifest.stagingDir, 'original_mid.snapshot.txt'), originalMid);

	const meta = loadMeta();
	meta.stagedAt = new Date().toISOString();
	meta.stageHelpers = stageHelpers;
	meta.stageFacade = stageFacade;
	meta.helpersSha = sha16(helpersSrc);
	meta.facadeSha = sha16(facadeSrc);
	meta.originalSha = sha16(raw);
	meta.usedValues = usedValues.sort();
	meta.usedTypes = usedTypes.sort();
	meta.originalMidSha = sha16(originalMid.replace(/\r\n/g, '\n').replace(/\n$/, ''));
	saveMeta(meta);

	ok(`staged ${stageHelpers}`);
	ok(`staged ${stageFacade}`);
	ok(`usedValues=${usedValues.length} usedTypes=${usedTypes.length}`);
}

function extractHelpersBodyFromStaged(src, nl) {
	const lines = src.split(/\r?\n/);
	let start = -1;
	for (let i = 0; i < lines.length; i++) {
		if (/^(export )?function isTodoWriteName\b/.test(lines[i])) {
			start = i;
			break;
		}
	}
	if (start < 0) fail('staged helpers: cannot find isTodoWriteName');

	let end = lines.length;
	// trim trailing export {…} / export type {…} blocks and blank lines
	while (end > start) {
		const t = lines[end - 1].trim();
		if (t === '') {
			end--;
			continue;
		}
		if (/^export \{/.test(t) || /^export type \{/.test(t)) {
			end--;
			continue;
		}
		break;
	}
	return lines.slice(start, end);
}

function extractCreateBodyFromStaged(src) {
	const lines = src.split(/\r?\n/);
	let start = -1;
	for (let i = 0; i < lines.length; i++) {
		if (/^export const useChatStore = create/.test(lines[i])) {
			start = i;
			break;
		}
	}
	if (start < 0) fail('staged facade: cannot find useChatStore');
	// drop trailing empty
	let end = lines.length;
	while (end > start && lines[end - 1].trim() === '') end--;
	return lines.slice(start, end);
}

function verify() {
	const meta = loadMeta();
	if (!meta.stageHelpers) fail('run stage first');

	const original = readText(manifest.source);
	const {nl, lines} = splitLines(original);
	const hr = manifest.helpersRange;
	const cr = manifest.createRange;
	const total = lines.length;
	const createTo = cr.to == null ? total : cr.to;
	const gap = sliceLines(lines, hr.to + 1, cr.from - 1);
	const originalMid = [
		...sliceLines(lines, hr.from, hr.to),
		...gap,
		...sliceLines(lines, cr.from, createTo),
	].join(nl);

	const helpersStaged = readText(meta.stageHelpers);
	const facadeStaged = readText(meta.stageFacade);

	let helperBody = extractHelpersBodyFromStaged(helpersStaged, nl);
	helperBody = helperBody.map(l => rewriteDeclLine(l, 'back'));
	let helperText = applyIdRewrite(helperBody.join(nl), 'back');

	let createBody = extractCreateBodyFromStaged(facadeStaged);
	let createText = applyIdRewrite(createBody.join(nl), 'back');

	const rebuilt = [helperText, ...gap.map(l => l), createText].join(nl);

	const norm = s => s.replace(/\r\n/g, '\n').replace(/\n$/, '');
	const a = norm(originalMid);
	const b = norm(rebuilt);

	if (a !== b) {
		const dump = path.join(manifest.stagingDir, '_verify_dump');
		writeText(path.join(dump, 'original_mid.ts.txt'), a + '\n');
		writeText(path.join(dump, 'rebuilt_mid.ts.txt'), b + '\n');
		const al = a.split('\n');
		const bl = b.split('\n');
		for (let i = 0; i < Math.max(al.length, bl.length); i++) {
			if (al[i] !== bl[i]) {
				console.error(`first diff at line ${i + 1}:`);
				console.error('  orig:', JSON.stringify(al[i]));
				console.error('  rebd:', JSON.stringify(bl[i]));
				break;
			}
		}
		fail(`round-trip mismatch; dumps in ${dump}`);
	}

	meta.verifiedAt = new Date().toISOString();
	meta.verifySha = sha16(a);
	saveMeta(meta);
	ok(`round-trip identical (${a.split('\n').length} lines, sha ${meta.verifySha})`);
}

function apply() {
	const meta = loadMeta();
	if (!meta.verifiedAt) fail('refuse apply: verify first');
	const liveSha = sha16(readText(manifest.source));
	if (liveSha !== meta.originalSha) {
		fail(`live sha drifted (${liveSha} vs ${meta.originalSha}); abort`);
	}
	fs.mkdirSync(abs('src/stores/chat'), {recursive: true});
	fs.copyFileSync(abs(meta.stageHelpers), abs(manifest.helpersOut));
	fs.copyFileSync(abs(meta.stageFacade), abs(manifest.facadeOut));
	meta.applied = true;
	meta.appliedAt = new Date().toISOString();
	saveMeta(meta);
	ok(`applied → ${manifest.helpersOut}`);
	ok(`applied → ${manifest.facadeOut}`);
}

function rollback() {
	const meta = loadMeta();
	if (!meta.backupFile || !fs.existsSync(abs(meta.backupFile))) {
		fail('no backup');
	}
	fs.copyFileSync(abs(meta.backupFile), abs(manifest.source));
	if (fs.existsSync(abs(manifest.helpersOut))) {
		fs.unlinkSync(abs(manifest.helpersOut));
		ok(`removed ${manifest.helpersOut}`);
	}
	meta.applied = false;
	meta.rolledBackAt = new Date().toISOString();
	saveMeta(meta);
	ok(`restored ${manifest.source} from backup`);
}

function captureDismantleTscErrors() {
	const tsc = spawnSync(
		process.platform === 'win32' ? 'npx.cmd' : 'npx',
		['tsc', '-b', '--pretty', 'false'],
		{cwd: root, encoding: 'utf8', shell: true},
	);
	const out = `${tsc.stdout || ''}${tsc.stderr || ''}`;
	const keys = new Set();
	for (const line of out.split(/\r?\n/)) {
		if (!/chatStore\.ts|preStoreHelpers\.ts/.test(line)) continue;
		if (/chatStore\.test\.ts|_staging/.test(line)) continue;
		const m = line.match(/error (TS\d+):\s*(.*)$/);
		if (m) keys.add(`${m[1]}|${m[2]}`);
	}
	return keys;
}

function test() {
	const globs = manifest.testGlobs || [];
	const vitest = spawnSync(
		process.platform === 'win32' ? 'npx.cmd' : 'npx',
		['vitest', 'run', ...globs],
		{cwd: root, stdio: 'inherit', shell: true},
	);
	if (vitest.status !== 0) fail(`vitest exited ${vitest.status}`);
	ok('vitest passed');

	const meta = loadMeta();
	const baseline = new Set(meta.baselineTscKeys || []);
	for (const k of manifest.allowNewTscKeys || []) baseline.add(k);
	const after = captureDismantleTscErrors();
	const introduced = [...after].filter(k => !baseline.has(k));
	if (introduced.length) {
		console.error('NEW typecheck errors vs pre-dismantle baseline:');
		for (const k of introduced) console.error(' ', k);
		fail(`introduced ${introduced.length} typecheck error(s)`);
	}
	ok(
		`typecheck gate: no new errors vs baseline (baseline=${baseline.size}, now=${after.size})`,
	);
}

function runAll() {
	backup();
	ok('capturing pre-dismantle tsc baseline for chatStore…');
	const baseline = captureDismantleTscErrors();
	const meta0 = loadMeta();
	meta0.baselineTscKeys = [...baseline];
	saveMeta(meta0);
	ok(`baseline keys: ${baseline.size}`);
	stage();
	verify();
	apply();
	const r = spawnSync(process.execPath, [__filename, 'test'], {
		cwd: root,
		stdio: 'inherit',
	});
	if (r.status !== 0) {
		console.error('TEST FAILED — rolling back live tree');
		rollback();
		process.exit(1);
	}
	const meta = loadMeta();
	meta.pipelineOkAt = new Date().toISOString();
	saveMeta(meta);
	ok('Phase A complete; backup retained for manual inspect');
}

function help() {
	console.log(`Phase A dismantle scheduler

  backup | stage | verify | apply | test | rollback | run

  run = backup → stage → verify → apply → test (rollback on fail)
`);
}

const map = {backup, stage, verify, apply, test, rollback, run: runAll, help};
if (!map[cmd]) {
	help();
	fail(`unknown: ${cmd}`);
}
map[cmd]();
