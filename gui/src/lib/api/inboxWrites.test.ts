import {afterEach, expect, it, vi} from 'vitest';
import {cancelInboxItem, editInboxItem} from '@/lib/api';
afterEach(() => vi.unstubAllGlobals());
it.each([{}, {ok: false}, {ok: true, session_id: 'other', queue_id: 'q'}])('cancel rejects an unconfirmed receipt %j', async payload => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
	expect(await cancelInboxItem('sid', 'q')).toBe(false);
});
it.each([{}, {ok: true, item: {queue_id: 'other', text: 'new'}}, {ok: true, item: {queue_id: 'q', text: 'old'}}])('edit rejects an unconfirmed receipt %j', async payload => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
	expect(await editInboxItem('sid', 'q', 'new')).toBe(false);
});
it('accepts matching edit and cancellation receipts', async () => {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ok: true, item: {queue_id: 'q', text: 'new'}})))
		.mockResolvedValueOnce(new Response(JSON.stringify({ok: true, session_id: 'sid', queue_id: 'q'}))));
	expect(await editInboxItem('sid', 'q', 'new')).toBe(true);
	expect(await cancelInboxItem('sid', 'q')).toBe(true);
});
