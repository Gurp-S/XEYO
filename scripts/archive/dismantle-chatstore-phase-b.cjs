#!/usr/bin/env node
/**
 * Dismantle scheduler — Phase B: extract multiAgentSlice from chatStore.ts.
 *
 * Pure text move, zero behavior change:
 * - Moves the multiAgent state fields + agent-view nav + agent task methods
 *   (pushAgentView … finalizeAgentStream, plus `...initAgentNav(),`) out of the
 *   create() literal into src/stores/chat/multiAgentSlice.ts.
 * - Facade spreads `...createMultiAgentSlice(set, get)` at the same position.
 * - Trims facade imports that become unused (api fns / SessionAgentMeta / initAgentNav).
 *
 * Pipeline: backup → tsc baseline → stage (staging only, live untouched) →
 * verify (byte round-trip) → apply → test (vitest + tsc gate) →
 * auto-rollback on failure.
 *
 * Usage:
 *   node scripts/dismantle-chatstore-phase-b.cjs backup|stage|verify|apply|test|rollback|run
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {spawnSync} = require('child_process');

const root = path.resolve(__dirname, '..');
const guiDir = root;

const manifest = {
	source: 'src/stores/chatStore.ts',
	sliceOut: 'src/stores/chat/multiAgentSlice.ts',
	backupDir: '.dismantle/phase-b/backup',
	stagingDir: '.dismantle/phase-b/staging',
	testGlobs: ['src/stores/chatStore.test.ts', 'src/stores/remoteStore.test.ts'],
	// Symbols expected to move with the block (import lines trimmed from facade).
	movedApiValues: ['loadAgentDetail', 'listSessionAgents', 'cancelSessionAgent', 'retrySessionAgent'],
	movedApiType: 'SessionAgentMeta',
	movedPreStore: ['initAgentNav'],
	// Import-line trim anchors for the byte round-trip in verify().
	trimAnchors: {
		loadAgentDetail: {before: '	loadServerSessionMessages,'},
		listSessionAgents: {
			block: ['	listSessionAgents,', '	cancelSessionAgent,', '	retrySessionAgent,'],
			before: '	resolveRollbackRecovery as resolveRollbackRecoveryRequest,',
		},
		SessionAgentMeta: {before: '	type UsageStreamEvent'},
		initAgentNav: {before: '	isRollbackSessionBusyError,'},
	},
};

const SLICE_KEYS = [
	'multiAgentTasksBySession',
	'agentsBySession',
	'agentTranscriptsById',
	'liveAgentTextById',
	'agentViewStack',
	'agentViewIndex',
	'pushAgentView',
	'backAgentView',
	'forwardAgentView',
	'resetAgentView',
	'openAgentView',
	'cancelAgentTask',
	'retryAgentTask',
	'loadAgentsFor',
	'ensureAgentTranscript',
	'appendAgentDelta',
	'finalizeAgentStream',
];

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
function metaPath() {
	return path.join(manifest.backupDir, 'PHASE_B_META.json');
}
function loadMeta() {
	const p = metaPath();
	if (!fs.existsSync(p)) return {};
	return JSON.parse(fs.readFileSync(p, 'utf8'));
}
function saveMeta(meta) {
	fs.mkdirSync(manifest.backupDir, {recursive: true});
	fs.writeFileSync(metaPath(), JSON.stringify(meta, null, 2));
}
function usedOnce(text, re) {
	const m = text.match(new RegExp(re.source, 'gm'));
	return m ? m.length : 0;
}

// --- anchored region location ------------------------------------------------

const FIELD_NAMES = ['multiAgentTasksBySession', 'agentsBySession', 'agentTranscriptsById', 'liveAgentTextById'];

function locateRegion(lines) {
	const fieldRe = new RegExp(`^\t(${FIELD_NAMES.join('|')}): \\{\\},$`);
	let fieldStart = -1;
	for (let i = 0; i < lines.length - FIELD_NAMES.length; i++) {
		if (fieldRe.test(lines[i])) {
			let all = true;
			for (let k = 0; k < FIELD_NAMES.length; k++) {
				if (!fieldRe.test(lines[i + k])) {
					all = false;
					break;
				}
			}
			if (all) {
				fieldStart = i;
				break;
			}
		}
	}
	if (fieldStart < 0) fail('anchor not found: 4 consecutive multiAgent state field lines');

	const initNavRe = /^\t\.\.\.initAgentNav\(\),$/;
	let initNavIdx = -1;
	for (let i = fieldStart + FIELD_NAMES.length; i < fieldStart + FIELD_NAMES.length + 4; i++) {
		if (initNavRe.test(lines[i])) {
			initNavIdx = i;
			break;
		}
	}
	if (initNavIdx < 0) fail('anchor not found: ...initAgentNav() spread after multiAgent fields');

	const pushRe = /^\tpushAgentView\(agentId\) \{$/;
	let methodStart = -1;
	for (let i = initNavIdx + 1; i < initNavIdx + 5; i++) {
		if (pushRe.test(lines[i])) {
			methodStart = i;
			break;
		}
	}
	if (methodStart < 0) fail('anchor not found: pushAgentView after initAgentNav');

	const hydrateRe = /^\tasync hydrate\(\) \{$/;
	let hydrateIdx = -1;
	for (let i = methodStart + 1; i < lines.length; i++) {
		if (hydrateRe.test(lines[i])) {
			hydrateIdx = i;
			break;
		}
	}
	if (hydrateIdx < 0) fail('anchor not found: hydrate() after pushAgentView');

	const region = lines.slice(fieldStart, hydrateIdx);
	const regionText = region.join('\n');
	for (const probe of ['finalizeAgentStream', 'appendAgentDelta', 'loadAgentsFor']) {
		if (!new RegExp(`\\b${probe}\\b`).test(regionText)) {
			fail(`region sanity: expected probe '${probe}' inside region`);
		}
	}
	// region must end with the finalizeAgentStream closer (allow trailing blanks)
	let lastNonBlank = region.length - 1;
	while (lastNonBlank >= 0 && region[lastNonBlank].trim() === '') lastNonBlank--;
	if (region[lastNonBlank] !== '\t},') {
		fail(`region sanity: expected region to end with '\\t},', got '${region[lastNonBlank]}'`);
	}
	return {fieldStart, initNavIdx, methodStart, hydrateIdx, region};
}

// --- pipeline steps ----------------------------------------------------------

function backup() {
	const raw = readText(manifest.source);
	const ts = new Date().toISOString().replace(/[:.]/g, '-');
	const dest = path.join(manifest.backupDir, `chatStore.ts.${ts}`);
	writeText(dest, raw);
	saveMeta({
		phase: 'B',
		backedUpAt: new Date().toISOString(),
		backupFile: dest,
		originalSha: sha16(raw),
		source: manifest.source,
		sliceOut: manifest.sliceOut,
		applied: false,
	});
	ok(`backup → ${dest}`);
	ok(`sha ${sha16(raw)}`);
}

function buildSlice(regionLines, nl) {
	const regionText = regionLines.join('\n');
	// assert expected external symbols are used inside region.
	// value symbols must appear as a *call* (an object key like `uid: x` or a
	// comment mention does not justify an import — TS6133 would fire).
	const expectCalls = [...manifest.movedApiValues, ...manifest.movedPreStore, 'activeBackendSessionId'];
	for (const sym of expectCalls) {
		if (!new RegExp(`\\b${sym}\\s*\\(`).test(regionText)) {
			fail(`slice import sanity: expected call '${sym}(' in moved region`);
		}
	}
	if (!new RegExp(`\\b${manifest.movedApiType}\\b`).test(regionText)) {
		fail(`slice import sanity: expected type '${manifest.movedApiType}' in moved region`);
	}

	const apiImport = [
		'import {',
		...manifest.movedApiValues
			.slice()
			.sort()
			.map(s => `\t${s},`),
		`\ttype ${manifest.movedApiType},`,
		"} from '@/lib/api';",
	].join(nl);

	const lines = [
		'/**',
		' * AUTO-GENERATED by dismantle-chatstore-phase-b.cjs (Phase B: multiAgentSlice).',
		' * multiAgent state fields + agent-view nav + agent task methods moved verbatim',
		' * from chatStore.ts create() body. Behavior unchanged; facade spreads',
		' * createMultiAgentSlice(set, get) at the former position.',
		' */',
		"import type {StoreApi} from 'zustand';",
		apiImport,
		'import {',
		'\tactiveBackendSessionId,',
		'\tinitAgentNav,',
		'\ttype ChatState,',
		"} from './preStoreHelpers';",
		'',
		'type SetState = StoreApi<ChatState>[\'setState\'];',
		'type GetState = StoreApi<ChatState>[\'getState\'];',
		'',
		`const SLICE_KEYS = [${SLICE_KEYS.map(k => `'${k}'`).join(', ')}] as const;`,
		'',
		'export function createMultiAgentSlice(',
		'\tset: SetState,',
		'\tget: GetState,',
		'): Pick<ChatState, (typeof SLICE_KEYS)[number]> {',
		'\treturn {',
		...regionLines,
		'\t};',
		'}',
		'',
	];
	return lines.join(nl);
}

function buildFacade(lines, region, regionStart, nl) {
	const regionEnd = regionStart + region.length; // exclusive
	if (lines.slice(regionStart, regionEnd).join('\n') !== region.join('\n')) {
		fail('internal: region mismatch');
	}
	let facadeLines = [
		...lines.slice(0, regionStart),
		'\t...createMultiAgentSlice(set, get),',
		'',
		...lines.slice(regionEnd),
	];
	const facadeText = () => facadeLines.join(nl);

	// 1) trim api import lines
	const apiLines = manifest.movedApiValues.map(s => `\t${s},`);
	apiLines.push(`\ttype ${manifest.movedApiType},`);
	for (const imp of apiLines) {
		const esc = imp.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const c = (facadeText().match(new RegExp('^' + esc + '$', 'gm')) || []).length;
		if (c !== 1) fail(`facade import trim: expected exactly one '${imp.trim()}' line, got ${c}`);
		facadeLines = facadeLines.filter(l => l !== imp);
	}
	// 2) trim initAgentNav from preStoreHelpers import
	const initNavImport = '\tinitAgentNav,';
	if (usedOnce(facadeText(), /^\tinitAgentNav,$/gm) !== 1) {
		fail("facade import trim: expected exactly one 'initAgentNav,' import line");
	}
	facadeLines = facadeLines.filter(l => l !== initNavImport);
	// 3) moved symbols must not appear anywhere else in the facade
	const facadeBody = facadeText();
	for (const sym of [...manifest.movedApiValues, manifest.movedApiType, ...manifest.movedPreStore]) {
		const c = usedOnce(facadeBody, new RegExp(`\\b${sym}\\b`, 'g'));
		if (c !== 0) fail(`facade still references moved symbol '${sym}' (${c}×)`);
	}
	// 4) add slice import right after the preStoreHelpers import close
	const anchor = "} from './chat/preStoreHelpers';";
	const idx = facadeLines.indexOf(anchor);
	if (idx < 0) fail('facade: preStoreHelpers import close line not found');
	facadeLines.splice(idx + 1, 0, "import {createMultiAgentSlice} from './chat/multiAgentSlice';");

	return facadeLines.join(nl);
}

function stage() {
	const raw = readText(manifest.source);
	const {nl, lines} = splitLines(raw);
	const loc = locateRegion(lines);
	const region = lines.slice(loc.fieldStart, loc.hydrateIdx);

	const sliceSrc = buildSlice(region, nl);
	const facadeSrc = buildFacade(lines, region, loc.fieldStart, nl);

	const stageSlice = path.join(manifest.stagingDir, 'multiAgentSlice.ts');
	const stageFacade = path.join(manifest.stagingDir, 'chatStore.ts');
	const stageRegion = path.join(manifest.stagingDir, 'movedRegion.snapshot.txt');
	writeText(stageSlice, sliceSrc);
	writeText(stageFacade, facadeSrc);
	writeText(stageRegion, region.join('\n'));

	const meta = loadMeta();
	meta.stagedAt = new Date().toISOString();
	meta.stageSlice = stageSlice;
	meta.stageFacade = stageFacade;
	meta.stageRegion = stageRegion;
	meta.sliceSha = sha16(sliceSrc);
	meta.facadeSha = sha16(facadeSrc);
	meta.originalSha = sha16(raw);
	meta.regionLines = region.length;
	saveMeta(meta);

	ok(`staged ${stageSlice} (${sliceSrc.split(nl).length} lines)`);
	ok(`staged ${stageFacade} (${facadeSrc.split(nl).length} lines)`);
	ok(`moved region: ${region.length} lines (L${loc.fieldStart + 1}–L${loc.hydrateIdx})`);
}

function verify() {
	const meta = loadMeta();
	if (!meta.stagedAt) fail('refuse verify: stage first');
	const raw = readText(manifest.source);
	const {nl, lines} = splitLines(raw);
	if (sha16(raw) !== meta.originalSha) fail('live file drifted since stage; abort');

	const regionText = fs.readFileSync(abs(meta.stageRegion), 'utf8');
	const regionLines = regionText.split('\n'); // snapshot normalized to \n
	const facadeSrc = fs.readFileSync(abs(meta.stageFacade), 'utf8');
	const sliceSrc = fs.readFileSync(abs(meta.stageSlice), 'utf8');

	// slice must contain the moved region verbatim (EOL-normalized compare)
	const normText = s => s.replace(/\r\n/g, '\n');
	if (!normText(sliceSrc).includes(normText(regionText))) {
		fail('verify: slice file does not contain moved region verbatim');
	}

	// byte round-trip: facade + region + import re-inserts == original
	let cur = splitLines(facadeSrc).lines;
	// remove slice import + spread/blank, reinsert region
	const spreadIdx = cur.indexOf('\t...createMultiAgentSlice(set, get),');
	if (spreadIdx < 0 || cur[spreadIdx + 1] !== '') fail('verify: staged facade shape unexpected');
	cur = [...cur.slice(0, spreadIdx), ...regionLines, ...cur.slice(spreadIdx + 2)];
	// remove slice import line
	const impIdx = cur.indexOf("import {createMultiAgentSlice} from './chat/multiAgentSlice';");
	if (impIdx < 0) fail('verify: slice import line not found');
	cur.splice(impIdx, 1);
	// re-insert trimmed import lines at their anchors
	const a = manifest.trimAnchors;
	const insertBefore = (anchorLine, ins) => {
		const i = cur.indexOf(anchorLine);
		if (i < 0) fail(`verify: anchor '${anchorLine.trim()}' not found`);
		cur.splice(i, 0, ...ins);
	};
	insertBefore(a.loadAgentDetail.before, ['	loadAgentDetail,']);
	insertBefore(a.listSessionAgents.before, a.listSessionAgents.block);
	insertBefore(a.SessionAgentMeta.before, [`	type ${manifest.movedApiType},`]);
	insertBefore(a.initAgentNav.before, ['	initAgentNav,']);

	const rebuilt = cur.join(nl);
	const norm = s => s.replace(/\r\n/g, '\n').replace(/\n$/, '');
	if (sha16(norm(rebuilt)) !== sha16(norm(raw))) {
		fail('verify: round-trip byte mismatch');
	}
	meta.verifiedAt = new Date().toISOString();
	meta.verifySha = sha16(norm(rebuilt));
	saveMeta(meta);
	ok(`round-trip identical (${rebuilt.split(/\r?\n/).length} lines, sha ${meta.verifySha})`);
}

function apply() {
	const meta = loadMeta();
	if (!meta.verifiedAt) fail('refuse apply: verify first');
	const liveSha = sha16(readText(manifest.source));
	if (liveSha !== meta.originalSha) {
		fail(`live sha drifted (${liveSha} vs ${meta.originalSha}); abort`);
	}
	fs.copyFileSync(abs(meta.stageSlice), abs(manifest.sliceOut));
	fs.copyFileSync(abs(meta.stageFacade), abs(manifest.source));
	meta.applied = true;
	meta.appliedAt = new Date().toISOString();
	saveMeta(meta);
	ok(`applied → ${manifest.sliceOut}`);
	ok(`applied → ${manifest.source}`);
}

function rollback() {
	const meta = loadMeta();
	if (!meta.backupFile || !fs.existsSync(abs(meta.backupFile))) fail('no backup');
	fs.copyFileSync(abs(meta.backupFile), abs(manifest.source));
	if (fs.existsSync(abs(manifest.sliceOut))) {
		fs.unlinkSync(abs(manifest.sliceOut));
		ok(`removed ${manifest.sliceOut}`);
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
		{cwd: guiDir, encoding: 'utf8', shell: true},
	);
	const out = `${tsc.stdout || ''}${tsc.stderr || ''}`;
	const keys = new Set();
	for (const line of out.split(/\r?\n/)) {
		if (!/chatStore\.ts|preStoreHelpers\.ts|multiAgentSlice\.ts/.test(line)) continue;
		if (/chatStore\.test\.ts|_staging/.test(line)) continue;
		const m = line.match(/error (TS\d+):\s*(.*)$/);
		if (m) keys.add(`${m[1]}|${m[2]}`);
	}
	return keys;
}

function test() {
	const vitest = spawnSync(
		process.platform === 'win32' ? 'npx.cmd' : 'npx',
		['vitest', 'run', ...manifest.testGlobs],
		{cwd: guiDir, stdio: 'inherit', shell: true},
	);
	if (vitest.status !== 0) fail(`vitest exited ${vitest.status}`);
	ok('vitest passed');

	const meta = loadMeta();
	const baseline = new Set(meta.baselineTscKeys || []);
	const after = captureDismantleTscErrors();
	const introduced = [...after].filter(k => !baseline.has(k));
	if (introduced.length) {
		console.error('NEW typecheck errors vs pre-dismantle baseline:');
		for (const k of introduced) console.error(' ', k);
		fail(`introduced ${introduced.length} typecheck error(s)`);
	}
	ok(`typecheck gate: no new errors vs baseline (baseline=${baseline.size}, now=${after.size})`);
}

function runAll() {
	backup();
	ok('capturing pre-dismantle tsc baseline for chatStore/multiAgentSlice…');
	const baseline = captureDismantleTscErrors();
	const meta0 = loadMeta();
	meta0.baselineTscKeys = [...baseline];
	saveMeta(meta0);
	ok(`baseline keys: ${baseline.size}`);
	stage();
	verify();
	apply();
	const r = spawnSync(process.execPath, [__filename, 'test'], {
		cwd: guiDir,
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
	ok('Phase B complete; backup retained for manual inspect');
}

function help() {
	console.log(`Phase B dismantle scheduler (multiAgentSlice)

  backup | stage | verify | apply | test | rollback | run

  run = backup → stage → verify → apply → test (rollback on fail)
`);
}

const cmd = process.argv[2] || 'help';
const map = {backup, stage, verify, apply, test, rollback, run: runAll, help};
if (!map[cmd]) {
	help();
	fail(`unknown: ${cmd}`);
}
map[cmd]();
