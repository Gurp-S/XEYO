import {act, cleanup, renderHook, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
vi.unmock('@/stores/settingsStore');
import {useSettingsStore} from '@/stores/settingsStore';
import {useChatStore} from '@/stores/chatStore';
import {syncQueuedRequestSettings, useQueuedRequestSettings} from './useQueuedRequestSettings';
import {resetComposerDraftsForTests, setComposerDraft} from '@/lib/composerDrafts';

beforeEach(() => {
  resetComposerDraftsForTests();
  useSettingsStore.setState({model: 'old', provider: 'fake', apiKey: '', profiles: [], activeProfileId: ''});
  useChatStore.setState({sessions: [], inboxBySession: {}, historyById: {}});
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});

it('serializes rapid settings changes and forwards the latest model/modes', async () => {
  let release!: () => void;
  const bodies: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
    bodies.push(JSON.parse(init.body));
    if (bodies.length === 1) await new Promise<void>(resolve => {release = resolve;});
    return Response.json({ok: true, session_id: 'serial'});
  }));
  const first = syncQueuedRequestSettings('serial', {agentMode: 'agent'});
  useSettingsStore.setState({model: 'latest'});
  const second = syncQueuedRequestSettings('serial', {agentMode: 'ask', multiAgent: true});
  expect(bodies).toHaveLength(1);
  release(); await Promise.all([first, second]);
  expect(bodies.map(body => body.model)).toEqual(['old', 'latest']);
  expect(bodies[1]).toMatchObject({agent_mode: 'ask', multi_agent: true});
});

it('real store subscription updates an inactive queued backend branch when model settings change', async () => {
  const bodies: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
    bodies.push(JSON.parse(init.body));
    return Response.json({ok: true, session_id: 'branch'});
  }));
  useChatStore.setState({sessions: [{id: 'queued'}] as never,
    inboxBySession: {queued: [{queue_id: 'q'}]} as never,
    historyById: {queued: {activeBranch: {branchId: 'branch', backendSessionId: 'branch'}}} as never});
  setComposerDraft('queued', {text: '', attachments: [], permissionMode: 'risk', agentMode: 'ask'});
  renderHook(() => useQueuedRequestSettings('other', {agentMode: 'agent'}));
  await waitFor(() => expect(bodies).toHaveLength(1));
  act(() => useSettingsStore.setState({model: 'new-model', outputCompact: true, outputMode: 'ultra', permissionMode: 'never'}));
  await waitFor(() => expect(bodies.at(-1)).toMatchObject({model: 'new-model', output_compact: true, output_mode: 'ultra', permission_mode: 'risk', agent_mode: 'ask'}));
});
