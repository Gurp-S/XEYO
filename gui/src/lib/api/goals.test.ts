import {afterEach, describe, expect, it, vi} from 'vitest';
import {fetchGoal, patchGoalAction} from './goals';

afterEach(() => vi.unstubAllGlobals());

describe('goal receipt validation', () => {
	it('only an empty object authoritatively means no bound goal', async () => {
		for (const payload of [null, [], {driver: {}}, {goal_id: 'broken', status: 'active'}, {error: 'bad'}]) {
			vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
			expect((await fetchGoal('s1')).ok).toBe(false);
		}
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}')));
		expect(await fetchGoal('s1')).toMatchObject({ok: true, goal: null});
	});
	it('a malformed successful PATCH cannot erase a goal and carries its identity', async () => {
		const fetch = vi.fn().mockResolvedValue(new Response('{}'));
		vi.stubGlobal('fetch', fetch);
		expect(await patchGoalAction('branch', 'pause', {goal_id: 'g1', revision: 2}))
			.toMatchObject({ok: false, message: 'receipt_invalid'});
		expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({action: 'pause', goal_id: 'g1', revision: 2});
	});
});
