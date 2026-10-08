import {useEffect, useRef} from 'react';
import {useSettingsStore} from '@/stores/settingsStore';
import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';
import {getComposerDraft, type PermissionMode} from '@/lib/composerDrafts';
import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout, formatErrorDetail, type ChatRequestOptions} from '@/lib/api/core';
import {currentRequestEnvironment} from '@/lib/api/requestEnvironment';
import {sessionErrorBannerPatch} from '@/lib/pendingForSession';
import {resumeInbox} from '@/lib/api';

type QueuedRequestOptions = ChatRequestOptions & {permissionMode?: PermissionMode};

type Desired = {signature: string; body: ReturnType<typeof currentRequestEnvironment>; headers: Record<string, string>};
type Write = {desired: Desired; applied?: string; running?: Promise<void>};
const writes = new Map<string, Write>();

/** Serialize settings writes so a delayed older request cannot win. */
export function syncQueuedRequestSettings(backendId: string, options: QueuedRequestOptions): Promise<void> {
  const body = {...currentRequestEnvironment(options, true),
    ...(options.permissionMode ? {permission_mode: options.permissionMode} : {})};
  const requestHeaders = new Headers(authHeaders());
  requestHeaders.set('Content-Type', 'application/json');
  const headers: Record<string, string> = {};
  requestHeaders.forEach((value, key) => {headers[key] = value;});
  const signature = JSON.stringify([body, headers]);
  let write = writes.get(backendId);
  if (!write) {write = {desired: {signature, body, headers}}; writes.set(backendId, write);}
  write.desired = {signature, body, headers};
  if (write.applied === signature && !write.running) return Promise.resolve();
  if (write.running) return write.running;
  const entry = write;
  entry.running = (async () => {
    while (entry.applied !== entry.desired.signature) {
      const desired = entry.desired;
      const response = await fetchWithTimeout(apiUrl(`/v1/sessions/${encodeURIComponent(backendId)}/request-environment`), {
        method: 'POST', headers: desired.headers, body: JSON.stringify(desired.body),
      });
      const receipt = await response.json();
      if (!response.ok || receipt?.ok !== true || receipt?.session_id !== backendId) {
        throw new Error(formatErrorDetail(receipt, response.status));
      }
      entry.applied = desired.signature;
    }
  })().finally(() => {entry.running = undefined;});
  return entry.running;
}

export async function resumeInboxUsingCurrentSettings(backendId: string, options: ChatRequestOptions, queueId?: string) {
  await syncQueuedRequestSettings(backendId, options);
  return resumeInbox(backendId, queueId);
}

export function useQueuedRequestSettings(sessionId: string | null, options: ChatRequestOptions) {
  const latest = useRef({sessionId, options}); latest.current = {sessionId, options};
  useEffect(() => {
    let stopped = false;
    const synchronize = () => {
      const state = useChatStore.getState();
      const backends = new Set(Object.entries(state.inboxBySession).filter(([, items]) => items.length)
        .map(([id]) => activeBackendSessionId(state.historyById, id)));
      for (const [id, write] of writes) if (!backends.has(id) && !write.running) writes.delete(id);
      for (const [id, items] of Object.entries(state.inboxBySession)) {
        if (!items.length || !state.sessions.some(session => session.id === id)) continue;
        const mode = id === latest.current.sessionId ? latest.current.options : getComposerDraft(id);
        const backend = activeBackendSessionId(state.historyById, id);
        void syncQueuedRequestSettings(backend, {
          agentMode: mode?.agentMode, multiAgent: mode?.multiAgent,
          reasoningEffort: mode?.reasoningEffort,
          permissionMode: id === latest.current.sessionId ? undefined : getComposerDraft(id)?.permissionMode,
        }).catch(error => {
          if (!stopped) useChatStore.setState(sessionErrorBannerPatch(id, `排队设置同步失败：${String(error)}`));
        });
      }
    };
    synchronize();
    const unsubscribeSettings = useSettingsStore.subscribe(synchronize);
    const unsubscribeChat = useChatStore.subscribe((state, previous) => {
      if (state.inboxBySession !== previous.inboxBySession || state.historyById !== previous.historyById || state.sessions !== previous.sessions) synchronize();
    });
    return () => {stopped = true; unsubscribeSettings(); unsubscribeChat();};
  }, [sessionId, options.agentMode, options.multiAgent, options.reasoningEffort]);
}
