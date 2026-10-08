import {beforeEach, expect, it, vi} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {rememberTranscriptSnapshot} from '@/lib/transcriptSnapshot';
import {canonicalSessionHistory} from './canonicalSessionHistory';

const api = vi.hoisted(() => ({task: vi.fn(), messages: vi.fn()}));
vi.mock('@/lib/api', async original => ({...await original<typeof import('@/lib/api')>(), fetchSessionTask: api.task, loadServerSessionMessages: api.messages}));
const task = {ok: true, session_id: 'backend', busy: false, waiting_permission: false, status: 'succeeded', turn_id: 't1', revision: 3, last_event_id: 7};
const user = (id: string): ChatMessage => ({id, role: 'user', text: id, createdAt: 1});
const answer = (id: string, text = 'answer'): ChatMessage => ({id, role: 'assistant', text, createdAt: 2});
const snapshot = (messages: ChatMessage[], changes = {}) => rememberTranscriptSnapshot(messages,
	{session_id: 'backend', transcript_found: true, degraded: false, skipped_lines: 0, read_errors: [], ...changes}, 'backend');
beforeEach(() => {vi.resetAllMocks(); api.task.mockResolvedValue(task); api.messages.mockResolvedValue(snapshot([user('u1'), answer('server')]));});

it('uses canonical output, retains unknown local input, and labels it as undelivered', async () => {
	const local = [user('u1'), user('lost-input'), answer('local-copy'), answer('server'), answer('local-fragment', 'partial')];
	const messages = await canonicalSessionHistory('backend', local, () => true);
	expect(messages?.filter(row => row.role === 'assistant').map(row => row.id)).toEqual(['server']);
	expect(messages?.find(row => row.id === 'lost-input')?.localUndelivered).toBe(true);
	expect(api.task).toHaveBeenCalledTimes(2);
});

it('retains accepted queued input and clears the marker once a row is delivered', async () => {
	const local = [user('u1'), {...user('pending'), queueState: 'queued' as const}, {...user('u2'), localUndelivered: true}, answer('local')];
	api.messages.mockResolvedValue(snapshot([user('u1'), answer('server'), user('u2')]));
	const messages = await canonicalSessionHistory('backend', local, () => true);
	expect(messages?.find(row => row.id === 'pending')?.queueState).toBe('queued');
	expect(messages?.find(row => row.id === 'u2')?.localUndelivered).toBeUndefined();
});

it.each([{busy: true}, {status: 'recovery_required'}, {session_id: 'other'}])('does not replace history for an unsettled or mismatched task %j', async changes => {
	api.task.mockResolvedValue({...task, ...changes});
	expect(await canonicalSessionHistory('backend', [answer('local')], () => true)).toBeNull();
	expect(api.messages).not.toHaveBeenCalled();
});

it.each([{turn_id: 'new'}, {revision: 4}, {last_event_id: 8}, {busy: true}])('does not replace history when the task changes during the read %j', async changes => {
	api.task.mockResolvedValueOnce(task).mockResolvedValueOnce({...task, ...changes});
	expect(await canonicalSessionHistory('backend', [answer('local')], () => true)).toBeNull();
});

it('does not replace history with a degraded second read', async () => {
	api.messages.mockResolvedValue(snapshot([user('u1')], {skipped_lines: 1}));
	expect(await canonicalSessionHistory('backend', [answer('local')], () => true)).toBeNull();
	expect(api.task).toHaveBeenCalledOnce();
});
