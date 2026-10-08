import {afterEach, expect, it, vi} from 'vitest';
import {abandonSessionRecovery} from '@/lib/api';

afterEach(() => vi.unstubAllGlobals());

it.each([{}, {ok: false, status: 'stopped', turn_id: 'old'}, {ok: true, status: 'running', turn_id: 'old'}, {ok: true, status: 'stopped', turn_id: 'new'}])('does not accept an invalid recovery receipt %j', async receipt => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt))));
	expect(await abandonSessionRecovery('backend', 'old')).toBe(false);
});

it('accepts only the requested stopped turn and sends its identity', async () => {
	const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ok: true, status: 'stopped', turn_id: 'old'})));
	vi.stubGlobal('fetch', fetch);
	expect(await abandonSessionRecovery('backend', 'old')).toBe(true);
	expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({turn_id: 'old'});
});
