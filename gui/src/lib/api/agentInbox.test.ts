import {afterEach, expect, it, vi} from 'vitest';
import {postAgentInbox, cancelAgentInbox} from '@/lib/api';

afterEach(() => vi.unstubAllGlobals());
it('sends a stable message identity and respects the acceptance receipt', async () => {
	const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ok: true, deliver: 'pending', messageId: 'm', inboxCount: 1})));
	vi.stubGlobal('fetch', fetch);
	expect(await postAgentInbox('branch-sid', 'a', 'hello', 'm')).toMatchObject({ok: true, messageId: 'm'});
	expect(String(fetch.mock.calls[0][0])).toContain('/branch-sid/agents/a/inbox');
	expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({text: 'hello', message_id: 'm'});
	fetch.mockResolvedValue(new Response(JSON.stringify({ok: false, deliver: 'pending'})));
	expect(await postAgentInbox('s', 'a', 'hello', 'm')).toBeNull();
});
it('does not report removal when the message was already delivered', async () => {
	const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ok: true, removed: false})));
	vi.stubGlobal('fetch', fetch);
	expect(await cancelAgentInbox('s', 'a', 'm')).toBe(false);
	fetch.mockResolvedValue(new Response(JSON.stringify({ok: true, removed: true})));
	expect(await cancelAgentInbox('s', 'a', 'm')).toBe(true);
});
