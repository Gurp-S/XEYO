/** Offline probes of current defects, deliberately outside normal regression suite. */
import {act, cleanup, render, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');
const {readGoal} = vi.hoisted(() => ({readGoal: vi.fn()}));
vi.mock('@/lib/api/goals', async original => ({
  ...await original<typeof import('@/lib/api/goals')>(),
  fetchGoal: readGoal,
}));

import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore} from '@/stores/settingsStore';
import {useSessionGoalLive} from '@/components/SessionGoalDock';
import {writeGoalState} from '@/lib/goalSync';
import {streamTurnEvents} from '@/lib/api/chatStream';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';
import type {GoalSnapshot} from '@/lib/api/goals';

const goal = (revision: number, status = 'active') => ({
  goal_id: 'g1', title: 'task', text: 'task', status, revision,
  rounds: 1, max_rounds: 0, pending_complete: false, blocked_reason: '',
} as GoalSnapshot);

function Poller() {useSessionGoalLive('s1'); return null;}

afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks();});

it('rejected send removes unresolved ask and plan before any request', async () => {
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  useSettingsStore.setState({apiKey: '', provider: 'deepseek'});
  useChatStore.setState({activeId: 's1', pendingAsk: {
    sessionId: 's1', requestId: 'ask1', question: 'q', options: [], questions: [],
  }, pendingPlan: {sessionId: 's1', requestId: 'plan1', plan: 'plan'}});
  const result = await useChatStore.getState().sendMessage('ordinary task');
  expect(result).toBe(false);
  expect(fetch).not.toHaveBeenCalled();
  expect(useChatStore.getState().pendingAsk).toBeNull();
  expect(useChatStore.getState().pendingPlan).toBeNull();
});

it('late polling response overwrites a newer mutation revision', async () => {
  let resolve!: (value: unknown) => void;
  readGoal.mockReturnValue(new Promise(r => {resolve = r;}));
  useChatStore.setState({sessionGoalById: {s1: {goal: goal(1), driver: null}}});
  render(<Poller />);
  await waitFor(() => expect(readGoal).toHaveBeenCalledOnce());
  act(() => writeGoalState('s1', {goal: goal(2, 'paused'), driver: null}));
  await act(async () => {
    resolve({ok: true, goal: goal(1), driver: null, message: ''});
    await Promise.resolve();
  });
  expect(useChatStore.getState().sessionGoalById.s1?.goal.revision).toBe(1);
  expect(useChatStore.getState().sessionGoalById.s1?.goal.status).toBe('active');
});

it('reattach silently discards goal and jobs while completing the stream', async () => {
  const encoder = new TextEncoder();
  const content = [
    {xy: {type: 'goal', goal: goal(2), session_id: 's1', turn_id: 't1', event_id: 1}},
    {xy: {type: 'jobs', jobs: [{job_id: 'j1'}], session_id: 's1', turn_id: 't1', event_id: 2}},
  ].map(frame => `data: ${JSON.stringify(frame)}\n\n`).join('') + 'data: [DONE]\n\n';
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream({
    start(c) {c.enqueue(encoder.encode(content)); c.close();},
  }), {status: 200})));
  const onGoal = vi.fn(), onJobs = vi.fn(), onDone = vi.fn(), onError = vi.fn();
  await streamTurnEvents('s1', 0, {onDelta: vi.fn(), onGoal, onJobs, onDone, onError});
  expect(onDone).toHaveBeenCalledOnce();
  expect(onError).not.toHaveBeenCalled();
  expect(onGoal).not.toHaveBeenCalled();
  expect(onJobs).not.toHaveBeenCalled();
});

it('malformed nonempty goal response is reported as authoritative absence', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/goals')>('@/lib/api/goals');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({unexpected: 'schema'}), {status: 200})));
  const result = await actual.fetchGoal('s1');
  expect(result.ok).toBe(true);
  expect(result.goal).toBeNull();
});

it('malformed successful goal mutation is accepted as a null goal', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/goals')>('@/lib/api/goals');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({unexpected: 'schema'}), {status: 200})));
  const result = await actual.patchGoalAction('s1', 'edit', {revision: 1, text: 'changed goal'});
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error('expected current malformed acceptance');
  expect(result.goal).toBeNull();
});

it('goal polling uses local session identity even when chat uses a different branch backend', async () => {
  useChatStore.setState({historyById: {s1: {activeBranch: {
    branchId: 'rewound', backendSessionId: 'branch-backend', parentBranchId: 'root',
    createdAt: 0, forkMessageId: null, label: 'branch',
  }, archivedBranches: []}}});
  readGoal.mockResolvedValue({ok: false, message: 'session not found'});
  render(<Poller />);
  await waitFor(() => expect(readGoal).toHaveBeenCalledWith('s1'));
  expect(activeBackendSessionId(useChatStore.getState().historyById, 's1')).toBe('branch-backend');
});
