#!/usr/bin/env node
/**
 * Dismantle scheduler — generic multi-region store-slice extractor for chatStore.ts.
 *
 * Same contract as phase A/B/C/D: pure text move, zero behavior change, byte
 * round-trip verification, auto-rollback on any gate failure.
 *
 * Specs:
 *   e = spaceSessionSlice  (hydrate + spaces/sessions CRUD, two regions)
 *   f = streamSendSlice    (sendMessage … abandonRecovery, two regions)
 *   g = uiChromeSlice      (chrome setters + clearErrorBanner, two regions)
 *
 * Concurrency safety: apply() refuses to write if the live file sha drifted
 * since stage(). Anchors are regex-based, never line-number-based.
 *
 * Usage:
 *   node scripts/dismantle-chatstore-slice.cjs <e|f|g> backup|stage|verify|apply|test|rollback|run
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {spawnSync} = require('child_process');

const guiDir = path.resolve(__dirname, '..');

const SPECS = {
	e: {
		id: 'e',
		title: 'spaceSessionSlice',
		sliceOut: 'src/stores/chat/spaceSessionSlice.ts',
		factory: 'createSpaceSessionSlice',
		regions: [
			{
				start: /^\tasync hydrate\(\) \{$/,
				end: /^\tsetSidebarOpen\(open\) \{$/,
				probes: ['hydrate', 'writePendingPermission'],
			},
			{
				start: /^\tasync setActiveSpace\(spaceId\) \{$/,
				end: /^\t{2,4}async sendMessage\($/,
				probes: ['toggleSpaceCollapsed', 'openFolder', 'createSession', 'selectSession', 'removeSession'],
			},
		],
		keys: ['hydrate', 'setActiveSpace', 'toggleSpaceCollapsed', 'openFolder', 'enterSpace', 'removeSpace', 'renameSpace', 'createSession', 'selectSession', 'removeSession'],
		testGlobs: ['src/stores/chatStore.test.ts', 'src/stores/remoteStore.test.ts'],
	},
	f: {
		id: 'f',
		title: 'streamSendSlice',
		sliceOut: 'src/stores/chat/streamSendSlice.ts',
		factory: 'createStreamSendSlice',
		regions: [
			{
				start: /^\t{2,4}async sendMessage\($/,
				end: /^\t\.\.\.createRemoteMirrorSlice\(set, get\),$/,
				probes: ['sendMessage'],
			},
			{
				start: /^\tasync stopGeneration\(\) \{$/,
				end: /^\}\)\);$/,
				probes: ['recoverStuckStream', 'reattachStream', 'continueRecovery', 'abandonRecovery'],
			},
		],
		keys: ['sendMessage', 'stopGeneration', 'recoverStuckStream', 'reattachActiveStreams', 'reattachStream', 'continueRecovery', 'abandonRecovery'],
		testGlobs: ['src/stores/chatStore.test.ts', 'src/stores/remoteStore.test.ts'],
	},
	g: {
		id: 'g',
		title: 'uiChromeSlice',
		sliceOut: 'src/stores/chat/uiChromeSlice.ts',
		factory: 'createUiChromeSlice',
		regions: [
			{
				start: /^\tsetSidebarOpen\(open\) \{$/,
				end: /^\t\.\.\.createStreamSendSlice\(set, get\),$/,
				probes: ['setSidebarOpen', 'setPendingPermission', 'requestComposerInsert', 'requestComposerFocus'],
			},
			{
				start: /^\t{2,4}clearErrorBanner\(\) \{$/,
				end: /^\}\)\);$/,
				probes: ['clearErrorBanner'],
			},
		],
		keys: ['setSidebarOpen', 'setPendingPermission', 'setPendingAsk', 'setPendingPlan', 'setAgentMode', 'requestSearchFocus', 'requestComposerInsert', 'requestComposerFocus', 'clearErrorBanner'],
		testGlobs: ['src/stores/chatStore.test.ts', 'src/stores/remoteStore.test.ts'],
	},
};

const SOURCE = 'src/stores/chatStore.ts';
const PRESTORE = 'src/stores/chat/preStoreHelpers.ts';

function fail(msg) {
	console.error(`FAIL: ${msg}`);
	process.exit(1);
}
function ok(msg) {
	console.log(`  ✓ ${msg}`);
}
function sha16(s) {
	return crypto.createHash('sha256').update(s).digest('hex').slice(0, 16);
}
function abs(rel) {
	return path.join(guiDir, rel);
}
function readText(rel) {
	return fs.readFileSync(abs(rel), 'utf8');
}
function writeText(rel, body) {
	fs.mkdirSync(path.dirname(abs(rel)), {recursive: true});
	fs.writeFileSync(abs(rel), body);
}
function splitLines(raw) {
	const nl = /\r\n/.test(raw) ? '\r\n' : '\n';
	return {nl, lines: raw.split(nl)};
}
const normText = s => s.replace(/\r\n/g, '\n');
function stripComments(text) {
	return text.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
}

function specDir(spec) {
	return `.dismantle/phase-${spec.id}`;
}
function metaPath(spec) {
	return path.join(specDir(spec), 'backup', 'META.json');
}
function loadMeta(spec) {
	const p = abs(metaPath(spec));
	if (!fs.existsSync(p)) return {};
	return JSON.parse(fs.readFileSync(p, 'utf8'));
}
function saveMeta(spec, meta) {
	writeText(metaPath(spec), JSON.stringify(meta, null, 2));
}

// --- import block parsing ----------------------------------------------------

function parseImportBlocks(lines) {
	const blocks = [];
	let i = 0;
	while (i < lines.length) {
		const line = lines[i];
		let m = line.match(/^import type \{(.*)\} from '([^']+)';$/);
		if (m) {
			blocks.push({
				module: m[2],
				single: true,
				allType: true,
				lineIdx: [i],
				items: m[1].split(',').filter(s => s.trim()).map(s => ({
					name: s.trim().replace(/^type\s+/, ''),
					local: s.trim().replace(/^type\s+/, ''),
					isType: true,
					raw: null,
				})),
			});
			i++;
			continue;
		}
		m = line.match(/^import \{(.*)\} from '([^']+)';$/);
		if (m) {
			blocks.push({
				module: m[2],
				single: true,
				allType: false,
				lineIdx: [i],
				items: m[1].split(',').filter(s => s.trim()).map(s => {
					const t = s.trim();
					const isType = /^type\s/.test(t);
					const name = t.replace(/^type\s+/, '');
					const am = name.match(/^([\w$]+)\s+as\s+([\w$]+)$/);
					return {name: am ? am[1] : name, local: am ? am[2] : name, isType, raw: null};
				}),
			});
			i++;
			continue;
		}
		if (/^import \{$/.test(line) || /^import type \{$/.test(line)) {
			const start = i;
			const allType = /^import type \{$/.test(line);
			const items = [];
			let j = i + 1;
			let module = null;
			while (j < lines.length) {
				const mm = lines[j].match(/^\} from '([^']+)';$/);
				if (mm) {
					module = mm[1];
					j++;
					break;
				}
				const it = lines[j].match(/^\t?(type )?([\w$]+)(?:\s+as\s+([\w$]+))?,?\s*$/);
				if (it) {
					items.push({
						name: it[2],
						local: it[3] || it[2],
						isType: allType || !!it[1],
						raw: lines[j],
					});
				}
				j++;
			}
			if (module) {
				blocks.push({module, single: false, allType, lineIdx: range(start, j), items});
			}
			i = j;
			continue;
		}
		i++;
	}
	return blocks;
}
function range(a, b) {
	const out = [];
	for (let k = a; k < b; k++) out.push(k);
	return out;
}

const W = 'A-Za-z0-9_$';
function symbolUsed(bodyText, local, isType) {
	// word boundary without backslash-b: not adjacent to an identifier char;
	// value usage must also not be a member access (`.local`) or a key (`local:`)
	const re = new RegExp(
		'(^|[^' + W + '.])' + local + '(?!\\s*:)($|[^' + W + '])',
		'g',
	);
	const occ = bodyText.match(re);
	return !!occ && occ.length > 0;
}

function scrapePreStoreExports() {
	const src = readText(PRESTORE);
	const names = new Set(['ChatState']);
	for (const m of src.matchAll(/^export (?:async )?(?:function|const|class) (\w+)/gm)) names.add(m[1]);
	for (const m of src.matchAll(/^export (?:type|interface) (\w+)/gm)) names.add(m[1]);
	const big = src.match(/^export \{([^}]+)\};/m);
	if (big) {
		for (const part of big[1].split(',')) {
			const t = part.trim();
			if (!t) continue;
			const am = t.match(/^([\w$]+)\s+as\s+([\w$]+)$/);
			names.add(am ? am[2] : t);
		}
	}
	return [...names];
}

// --- region location ---------------------------------------------------------

function locateRegions(lines, spec) {
	const out = [];
	let cursor = 0;
	for (const r of spec.regions) {
		let start = -1;
		for (let i = cursor; i < lines.length; i++) {
			if (r.start.test(lines[i])) {
				start = i;
				break;
			}
		}
		if (start < 0) fail(`anchor not found: start (${r.start})`);
		let end = -1;
		if (r.end) {
			for (let i = start + 1; i < lines.length; i++) {
				if (r.end.test(lines[i])) {
					end = i;
					break;
				}
			}
			if (end < 0) fail(`anchor not found: end (${r.end})`);
		} else {
			end = lines.length;
		}
		let region = lines.slice(start, end);
		while (region.length && region[region.length - 1].trim() === '') region.pop();
		const text = region.join('\n');
		for (const probe of r.probes) {
			if (!new RegExp(`\\b${probe}\\b`).test(text)) {
				fail(`region sanity: probe '${probe}' missing`);
			}
		}
		if (!/^\t+\},$/.test(region[region.length - 1]) && !/^\}\)\);$/.test(region[region.length - 1])) {
			fail(`region sanity: unexpected last line '${region[region.length - 1]}'`);
		}
		out.push({start, end, region});
		cursor = end;
	}
	return out;
}

// --- slice / facade builders -------------------------------------------------

function buildSlice(spec, regions, facadeLines, nl) {
	const regionLinesFlat = [];
	regions.forEach((r, i) => {
		if (i > 0) regionLinesFlat.push('');
		regionLinesFlat.push(...r.region);
	});
	const regionText = regionLinesFlat.join('\n');
	const stripped = stripComments(regionText);

	const parsed = parseImportBlocks(facadeLines);
	const usedByModule = [];
	for (const block of parsed) {
		if (block.module === './chat/preStoreHelpers') continue;
		const items = block.items.filter(it => symbolUsed(stripped, it.local, it.isType));
		if (items.length) usedByModule.push({module: block.module, items});
	}
	const preNames = scrapePreStoreExports();
	const preUsed = preNames.filter(n => n !== 'ChatState' && symbolUsed(stripped, n, false));

	for (const k of spec.keys) {
		if (!new RegExp(`\\b${k}\\b`).test(stripped)) {
			fail(`slice sanity: key '${k}' not found in moved regions`);
		}
	}

	const emit = it => (it.local !== it.name ? `${it.name} as ${it.local}` : it.local);
	const out = [];
	out.push(
		'/**',
		` * AUTO-GENERATED by dismantle-chatstore-slice.cjs (Phase ${spec.id.toUpperCase()}: ${spec.title}).`,
		` * Methods moved verbatim from chatStore.ts create() body. Behavior unchanged;`,
		` * facade spreads ${spec.factory}(set, get) at the former position.`,
		' */',
		"import type {StoreApi} from 'zustand';",
	);
	for (const {module, items} of usedByModule) {
		const values = items.filter(it => !it.isType).map(emit).sort();
		const types = items.filter(it => it.isType).map(emit).sort();
		out.push('import {');
		for (const v of values) out.push(`\t${v},`);
		for (const t of types) out.push(`\ttype ${t},`);
		out.push(`} from '${module}';`);
	}
	if (preUsed.length) {
		out.push('import {');
		for (const v of preUsed.slice().sort()) out.push(`\t${v},`);
		out.push('\ttype ChatState,');
		out.push("} from './preStoreHelpers';");
	} else {
		out.push("import type {ChatState} from './preStoreHelpers';");
	}
	out.push(
		'',
		"type SetState = StoreApi<ChatState>['setState'];",
		"type GetState = StoreApi<ChatState>['getState'];",
		'',
		`const SLICE_KEYS = [${spec.keys.map(k => `'${k}'`).join(', ')}] as const;`,
		'',
		`export function ${spec.factory}(`,
		'\tset: SetState,',
		'\tget: GetState,',
		'): Pick<ChatState, (typeof SLICE_KEYS)[number]> {',
		'\treturn {',
		...regionLinesFlat,
		'\t};',
		'}',
		'',
	);
	return {src: out.join(nl), usedByModule, preUsed};
}

function buildFacade(spec, lines, regions, nl) {
	const spreadLine = `\t...${spec.factory}(set, get),`;
	let out = [];
	let cursor = 0;
	regions.forEach((r, i) => {
		out.push(...lines.slice(cursor, r.start));
		if (i === 0) out.push(spreadLine, '');
		cursor = r.end;
	});
	out.push(...lines.slice(cursor));

	const blockEdits = [];
	for (;;) {
		const parsed = parseImportBlocks(out);
		const importIdx = new Set();
		for (const b of parsed) for (const i of b.lineIdx) importIdx.add(i);
		const bodyText = stripComments(out.filter((_, i) => !importIdx.has(i)).join('\n'));
		let edited = false;
		for (const block of parsed) {
			const kept = block.items.filter(it => symbolUsed(bodyText, it.local, it.isType));
			if (kept.length === block.items.length) continue;
			const originalLines = block.lineIdx.map(i => out[i]);
			let newLines;
			if (block.single) {
				const emit = it => {
					const base = it.local !== it.name ? `${it.name} as ${it.local}` : it.local;
					return it.isType ? `type ${base}` : base;
				};
				const body = kept.map(emit).join(', ');
				const prefix = block.items.every(it => it.isType) ? 'import type ' : 'import ';
				newLines = [`${prefix}{${body}} from '${block.module}';`];
			} else {
				newLines = [block.allType ? 'import type {' : 'import {'];
				for (const it of kept) newLines.push(it.raw);
				newLines.push(`} from '${block.module}';`);
			}
			out.splice(block.lineIdx[0], block.lineIdx.length, ...newLines);
			blockEdits.push({module: block.module, originalLines, rebuiltLines: newLines});
			edited = true;
			break;
		}
		if (!edited) break;
	}
	const anchor = "} from './chat/preStoreHelpers';";
	const anchorIdx = out.indexOf(anchor);
	if (anchorIdx < 0) fail('facade: preStoreHelpers import close line not found');
	const sliceModule = `./chat/${path.basename(spec.sliceOut, '.ts')}`;
	out.splice(anchorIdx + 1, 0, `import {${spec.factory}} from '${sliceModule}';`);
	return {src: out.join(nl), blockEdits};
}

// --- pipeline ----------------------------------------------------------------

function backup(spec) {
	const raw = readText(SOURCE);
	const ts = new Date().toISOString().replace(/[:.]/g, '-');
	const dest = path.join(specDir(spec), 'backup', `chatStore.ts.${ts}`);
	writeText(dest, raw);
	saveMeta(spec, {
		phase: spec.id.toUpperCase(),
		title: spec.title,
		backedUpAt: new Date().toISOString(),
		backupFile: dest,
		originalSha: sha16(raw),
		source: SOURCE,
		sliceOut: spec.sliceOut,
		applied: false,
	});
	ok(`backup → ${dest}`);
	ok(`sha ${sha16(raw)}`);
}

function stage(spec) {
	const raw = readText(SOURCE);
	const {nl, lines} = splitLines(raw);
	const regions = locateRegions(lines, spec);
	const slice = buildSlice(spec, regions, lines, nl);
	const facade = buildFacade(spec, lines, regions, nl);

	const stageSlice = path.join(specDir(spec), 'staging', path.basename(spec.sliceOut));
	const stageFacade = path.join(specDir(spec), 'staging', 'chatStore.ts');
	writeText(stageSlice, slice.src);
	writeText(stageFacade, facade.src);

	const regionMetas = [];
	regions.forEach((r, i) => {
		const snap = path.join(specDir(spec), 'staging', `movedRegion-${i}.snapshot.txt`);
		writeText(snap, r.region.join('\n'));
		// blank lines trimmed off the region tail (must be restored on verify)
		const trailingBlanks = r.end - r.start - r.region.length;
		// line that followed the region in the original (null → region ended at EOF)
		const afterLine = r.end < lines.length ? lines[r.end] : null;
		regionMetas.push({snapshot: snap, afterLine, trailingBlanks, lineCount: r.region.length});
	});

	const meta = loadMeta(spec);
	meta.stagedAt = new Date().toISOString();
	meta.stageSlice = stageSlice;
	meta.stageFacade = stageFacade;
	meta.regions = regionMetas;
	meta.sliceSha = sha16(slice.src);
	meta.facadeSha = sha16(facade.src);
	meta.originalSha = sha16(raw);
	meta.blockEdits = facade.blockEdits;
	meta.usedByModule = slice.usedByModule.map(u => ({module: u.module, symbols: u.items.map(i => i.local + (i.isType ? '(T)' : ''))}));
	meta.preUsed = slice.preUsed;
	saveMeta(spec, meta);

	ok(`staged ${stageSlice} (${slice.src.split(nl).length} lines)`);
	ok(`staged ${stageFacade} (${facade.src.split(nl).length} lines)`);
	regions.forEach((r, i) => ok(`region ${i}: ${r.region.length} lines (L${r.start + 1}–L${r.end})`));
	ok(`slice imports: ${meta.usedByModule.map(u => u.module + '{' + u.symbols.join(',') + '}').join(' ')} ${meta.preUsed.length ? '+ preStore{' + meta.preUsed.join(',') + '}' : ''}`);
}

function verify(spec) {
	const meta = loadMeta(spec);
	if (!meta.stagedAt) fail('refuse verify: stage first');
	const raw = readText(SOURCE);
	const {nl, lines} = splitLines(raw);
	if (sha16(raw) !== meta.originalSha) fail('live file drifted since stage; abort');

	const facadeSrc = fs.readFileSync(abs(meta.stageFacade), 'utf8');
	const sliceSrc = fs.readFileSync(abs(meta.stageSlice), 'utf8');

	let cur = splitLines(facadeSrc).lines;

	// region 0 lives behind the spread line
	const spreadLine = `\t...${spec.factory}(set, get),`;
	const spreadIdx = cur.indexOf(spreadLine);
	if (spreadIdx < 0 || cur[spreadIdx + 1] !== '') fail('verify: staged facade shape unexpected');
	const region0 = fs.readFileSync(abs(meta.regions[0].snapshot), 'utf8').split('\n');
	const pad0 = Array(meta.regions[0].trailingBlanks || 0).fill('');
	cur = [...cur.slice(0, spreadIdx), ...region0, ...pad0, ...cur.slice(spreadIdx + 2)];

	// regions 1..n are re-inserted before their recorded following line
	for (let i = 1; i < meta.regions.length; i++) {
		const regionLines = fs.readFileSync(abs(meta.regions[i].snapshot), 'utf8').split('\n');
		const pad = Array(meta.regions[i].trailingBlanks || 0).fill('');
		const after = meta.regions[i].afterLine;
		if (after === null) {
			while (cur.length && cur[cur.length - 1] === '') cur.pop();
			cur.push(...regionLines, ...pad, '');
		} else {
			const hits = [];
			for (let j = 0; j < cur.length; j++) {
				if (cur[j] === after) hits.push(j);
			}
			if (hits.length !== 1) fail(`verify: afterLine for region ${i} not unique ('${after.slice(0, 40)}')`);
			cur.splice(hits[0], 0, ...regionLines, ...pad);
		}
	}

	// remove slice import line
	const impIdx = cur.findIndex(l => l.startsWith(`import {${spec.factory}`));
	if (impIdx < 0) fail('verify: slice import line not found');
	cur.splice(impIdx, 1);

	// restore trimmed import blocks
	for (const edit of meta.blockEdits || []) {
		const modEsc = edit.module.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		if (edit.originalLines.length === 1) {
			// locate by the exact rebuilt line text (unique per edit)
			const hits = [];
			for (let i = 0; i < cur.length; i++) {
				if (cur[i] === edit.rebuiltLines[0]) hits.push(i);
			}
			if (hits.length !== 1) fail(`verify: rebuilt import line for '${edit.module}' not unique`);
			cur.splice(hits[0], 1, ...edit.originalLines);
		} else {
			const closeRe = new RegExp(`^\\} from '${modEsc}';$`);
			const hits = [];
			for (let i = 0; i < cur.length; i++) {
				if (closeRe.test(cur[i])) hits.push(i);
			}
			if (hits.length !== 1) fail(`verify: import block for '${edit.module}' not unique`);
			const closeAt = hits[0];
			let startAt = closeAt - 1;
			while (startAt >= 0 && !/^import (?:type )?\{$/.test(cur[startAt])) startAt--;
			if (startAt < 0) fail(`verify: import block start for '${edit.module}' not found`);
			cur.splice(startAt, closeAt - startAt + 1, ...edit.originalLines);
		}
	}

	const rebuilt = cur.join(nl);
	if (sha16(normText(rebuilt)) !== sha16(normText(raw))) {
		fail('verify: round-trip byte mismatch');
	}
	if (!normText(sliceSrc).includes(normText(region0.join('\n')))) {
		fail('verify: slice does not contain region 0 verbatim');
	}
	meta.verifiedAt = new Date().toISOString();
	meta.verifySha = sha16(normText(rebuilt));
	saveMeta(spec, meta);
	ok(`round-trip identical (${rebuilt.split(/\r?\n/).length} lines, sha ${meta.verifySha})`);
}

function apply(spec) {
	const meta = loadMeta(spec);
	if (!meta.verifiedAt) fail('refuse apply: verify first');
	const liveSha = sha16(readText(SOURCE));
	if (liveSha !== meta.originalSha) {
		fail(`live sha drifted (${liveSha} vs ${meta.originalSha}) — concurrent edit detected; abort`);
	}
	fs.mkdirSync(path.dirname(abs(spec.sliceOut)), {recursive: true});
	fs.copyFileSync(abs(meta.stageSlice), abs(spec.sliceOut));
	fs.copyFileSync(abs(meta.stageFacade), abs(SOURCE));
	meta.applied = true;
	meta.appliedAt = new Date().toISOString();
	saveMeta(spec, meta);
	ok(`applied → ${spec.sliceOut}`);
	ok(`applied → ${SOURCE}`);
}

function rollback(spec) {
	const meta = loadMeta(spec);
	if (!meta.backupFile || !fs.existsSync(abs(meta.backupFile))) fail('no backup');
	fs.copyFileSync(abs(meta.backupFile), abs(SOURCE));
	if (fs.existsSync(abs(spec.sliceOut))) {
		fs.unlinkSync(abs(spec.sliceOut));
		ok(`removed ${spec.sliceOut}`);
	}
	meta.applied = false;
	meta.rolledBackAt = new Date().toISOString();
	saveMeta(spec, meta);
	ok(`restored ${SOURCE} from backup`);
}

function captureTscErrors() {
	const tsc = spawnSync(
		process.platform === 'win32' ? 'npx.cmd' : 'npx',
		['tsc', '-b', '--pretty', 'false'],
		{cwd: guiDir, encoding: 'utf8', shell: true},
	);
	const out = `${tsc.stdout || ''}${tsc.stderr || ''}`;
	const keys = new Set();
	for (const line of out.split(/\r?\n/)) {
		if (!/chatStore\.ts|preStoreHelpers\.ts|Slice\.ts/.test(line)) continue;
		if (/chatStore\.test\.ts|_staging/.test(line)) continue;
		const m = line.match(/error (TS\d+):\s*(.*)$/);
		if (m) keys.add(`${m[1]}|${m[2]}`);
	}
	return keys;
}

function test(spec) {
	const vitest = spawnSync(
		process.platform === 'win32' ? 'npx.cmd' : 'npx',
		['vitest', 'run', ...spec.testGlobs],
		{cwd: guiDir, stdio: 'inherit', shell: true},
	);
	if (vitest.status !== 0) fail(`vitest exited ${vitest.status}`);
	ok('vitest passed');

	const meta = loadMeta(spec);
	const baseline = new Set(meta.baselineTscKeys || []);
	const after = captureTscErrors();
	const introduced = [...after].filter(k => !baseline.has(k));
	if (introduced.length) {
		console.error('NEW typecheck errors vs pre-dismantle baseline:');
		for (const k of introduced) console.error(' ', k);
		fail(`introduced ${introduced.length} typecheck error(s)`);
	}
	ok(`typecheck gate: no new errors vs baseline (baseline=${baseline.size}, now=${after.size})`);
}

function runAll(spec) {
	backup(spec);
	ok('capturing pre-dismantle tsc baseline…');
	const baseline = captureTscErrors();
	const meta0 = loadMeta(spec);
	meta0.baselineTscKeys = [...baseline];
	saveMeta(spec, meta0);
	ok(`baseline keys: ${baseline.size}`);
	stage(spec);
	verify(spec);
	apply(spec);
	const r = spawnSync(process.execPath, [__filename, spec.id, 'test'], {
		cwd: guiDir,
		stdio: 'inherit',
	});
	if (r.status !== 0) {
		console.error('TEST FAILED — rolling back live tree');
		rollback(spec);
		process.exit(1);
	}
	const meta = loadMeta(spec);
	meta.pipelineOkAt = new Date().toISOString();
	saveMeta(spec, meta);
	ok(`Phase ${spec.id.toUpperCase()} (${spec.title}) complete; backup retained`);
}

function help() {
	console.log(`Generic multi-region slice dismantle scheduler

  node scripts/dismantle-chatstore-slice.cjs <e|f|g> backup|stage|verify|apply|test|rollback|run
  e = spaceSessionSlice, f = streamSendSlice, g = uiChromeSlice
`);
}

const [, , specKey, cmd] = process.argv;
const spec = SPECS[specKey];
if (!spec) {
	help();
	fail(`unknown spec: ${specKey}`);
}
const map = {backup, stage, verify, apply, test, rollback, run: runAll, help};
if (!map[cmd]) {
	help();
	fail(`unknown cmd: ${cmd}`);
}
map[cmd](spec);
