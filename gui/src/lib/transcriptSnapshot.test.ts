import {afterEach, expect, it, vi} from 'vitest';
import {loadServerSessionMessages} from './api';
import {transcriptSnapshotInfo} from './transcriptSnapshot';

afterEach(() => vi.unstubAllGlobals());
const clean = {session_id: 's1', transcript_found: true, degraded: false, skipped_lines: 0, read_errors: [],
	messages: [{id: 'u1', role: 'user', text: '[Resume] Original goal: x\nUser cue: 继续', createdAt: 1}]};

it.each([
	['complete', {}, true],
	['skipped row', {skipped_lines: 1}, false],
	['read error', {read_errors: [{path: 'old', error: 'Permission denied'}]}, false],
	['degraded', {degraded: true}, false],
	['unknown identity', {session_id: 'other'}, false],
	['no transcript', {transcript_found: false}, false],
	['missing field', {read_errors: undefined}, false],
] as const)('preserves %s transport facts across Resume text restoration', async (_name, change, complete) => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({...clean, ...change}), {status: 200})));
	const messages = await loadServerSessionMessages('s1');
	expect(messages[0]?.text).toBe('继续');
	expect(transcriptSnapshotInfo(messages)).toEqual({complete});
});
