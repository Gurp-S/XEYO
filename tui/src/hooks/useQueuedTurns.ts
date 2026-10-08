import {useEffect, useRef, useState} from 'react';
import {consumeChatStream} from '../api/consumeChatStream.js';
import {deltaText, extractXy, getSessionMessages, parseDataLine, type AcceptedPayload} from '../api/sse.js';
import {mergeQueuedTimeline, messagesToItems} from '../lib/queuedTimeline.js';
import type {CliConfig, TimelineItem} from '../types.js';

type Item = {queue_id: string; message_id?: string; delivery_id?: string; state: string};
type Options = {
  config: CliConfig;
  abortRef: {current: AbortController | null};
  setItems: (update: (items: TimelineItem[]) => TimelineItem[]) => void;
  setBusy: (busy: boolean) => void;
  onXy: (xy: Record<string, unknown>) => void;
  onError: (message: string) => void;
  modesTouched: boolean;
};

/** Recover durable queue receipts and follow their turns independently of HTTP sends. */
export function useQueuedTurns(options: Options) {
  const current = useRef(options); current.current = options;
  const pending = useRef(new Map<string, {messageId: string; noteId: string}>());
  const [version, setVersion] = useState(0);
  const [paused, setPaused] = useState(false);
  const settingsWrites = useRef(Promise.resolve());
  useEffect(() => {
    pending.current.clear();
    setPaused(false);
  }, [options.config.sessionId]);
  useEffect(() => {
    if (!pending.current.size) return;
    const {config, modesTouched} = options;
    const headers: Record<string, string> = {'Content-Type': 'application/json'};
    if (config.apiKey) headers.Authorization = `Bearer ${config.apiKey}`;
    let stopped = false;
    const sendSettings = () => fetch(`${config.baseUrl.replace(/\/$/, '')}/v1/sessions/${encodeURIComponent(config.sessionId)}/request-environment`, {
      method: 'POST', headers,
      body: JSON.stringify({model: config.model, provider: config.provider,
        ...(modesTouched ? {permission_mode: config.permissionMode, agent_mode: config.agentMode,
          output_compact: config.outputCompact, output_mode: config.outputMode,
          code_compact: config.codeCompact, code_mode: config.codeMode} : {}),
      }),
    }).then(async response => {
      const receipt = await response.json();
      if (!response.ok || receipt?.ok !== true || receipt?.session_id !== config.sessionId) throw new Error(`settings update failed: HTTP ${response.status}`);
    });
    settingsWrites.current = settingsWrites.current.catch(() => {}).then(sendSettings);
    void settingsWrites.current.catch(error => {if (!stopped) current.current.onError(String(error));});
    return () => {stopped = true;};
  }, [options.config, options.modesTouched, version]);
  useEffect(() => {
    if (current.current.config.demo) return;
    const {config} = current.current;
    const root = `${config.baseUrl.replace(/\/$/, '')}/v1/sessions/${encodeURIComponent(config.sessionId)}`;
    const headers: Record<string, string> = config.apiKey ? {Authorization: `Bearer ${config.apiKey}`} : {};
    let stopped = false;
    let following = false;
    let controller: AbortController | undefined;
    let completedTurn = '';
    let cursorTurn = '';
    let cursor = 0;
    const texts = new Map<string, string>();
    const liveIds = new Set<string>();
    const request = async (suffix: string, init?: RequestInit) => {
      const requestHeaders = new Headers(init?.headers);
      for (const [name, value] of Object.entries(headers)) requestHeaders.set(name, value);
      const response = await fetch(root + suffix, {...init, headers: requestHeaders});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response;
    };
    async function synchronize(items: Item[]) {
      const loaded = await getSessionMessages(config.baseUrl, config.apiKey, config.sessionId);
      if (stopped) return;
      const ids = new Set(loaded.messages.map(message => message.id));
      const completed = items.filter(item => item.state === 'delivered' && ids.has(item.delivery_id || item.message_id || ''));
      const removed = new Set<string>();
      for (const item of completed) {
        const receipt = pending.current.get(item.queue_id);
        if (receipt) {
          removed.add(receipt.noteId);
          if (receipt.messageId !== item.delivery_id) removed.add(receipt.messageId);
        }
        if (item.message_id && item.message_id !== item.delivery_id) removed.add(item.message_id);
      }
      current.current.setItems(local => mergeQueuedTimeline(local, messagesToItems(loaded.messages), removed));
      if (completed.length) {
        await request('/inbox/ack', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({queue_ids: completed.map(item => item.queue_id)})});
        if (stopped) return;
        for (const item of completed) pending.current.delete(item.queue_id);
      }
    }
    async function follow(turnId: string) {
      following = true;
      if (cursorTurn !== turnId) {
        cursorTurn = turnId; cursor = 0; texts.clear(); liveIds.clear();
      }
      controller = new AbortController();
      const ac = controller;
      current.current.abortRef.current = ac;
      current.current.setBusy(true);
      let completed = false;
      try {
        const response = await request(`/turns/current/events?cursor=${cursor}`, {signal: ac.signal});
        if (!response.body) throw new Error('empty response body');
        await consumeChatStream(response.body, {
          onDelta() {}, onXy() {}, onDone() {completed = true;},
          onError(error) {if (!stopped) current.current.onError(error.message);},
        }, line => {
          if (stopped) return;
          const object = parseDataLine(line); if (!object) return;
          const xy = extractXy(object);
          const frameTurn = object.xeyo_turn_id || xy?.turn_id;
          if (frameTurn && frameTurn !== turnId) return;
          const eventId = object.xeyo_event_id ?? xy?.event_id;
          if (typeof eventId === 'number' && Number.isSafeInteger(eventId) && eventId > 0) {
            if (eventId <= cursor) return;
            cursor = eventId;
          }
          const text = deltaText(object);
          if (text) {
            const id = typeof object.xeyo_message_id === 'string' ? object.xeyo_message_id : `queued-${turnId}`;
            texts.set(id, (texts.get(id) || '') + text); liveIds.add(id);
            const prefix = texts.get(id)!;
            current.current.setItems(local => {
              const exists = local.some(item => item.id === id);
              const updated = local.map(item => item.kind === 'assistant' && item.id === id
                ? {...item, text: item.text.length > prefix.length ? item.text : prefix, streaming: true} : item);
              return exists ? updated : [...updated, {id, kind: 'assistant', text: prefix, streaming: true}];
            });
          }
          if (xy) current.current.onXy(xy);
        }, ac.signal);
      } catch (error) {
        if (!stopped && !ac.signal.aborted) current.current.onError(String(error));
      } finally {
        if (completed && !ac.signal.aborted) completedTurn = turnId;
        if (!stopped && current.current.abortRef.current === ac) {
          current.current.abortRef.current = null;
          current.current.setBusy(false);
          current.current.setItems(local => local.map(item => item.kind === 'assistant' && liveIds.has(item.id) ? {...item, streaming: false} : item));
        }
        following = false;
      }
    }
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        if (!following && !current.current.abortRef.current) {
          const inbox = await (await request('/inbox')).json();
          if (!Array.isArray(inbox.items)) throw new Error('inbox receipt missing items');
          if (stopped) return;
          if (!stopped) setPaused(inbox.paused === true);
          const wasEmpty = pending.current.size === 0;
          for (const item of inbox.items as Item[]) {
            if (!pending.current.has(item.queue_id)) pending.current.set(item.queue_id, {messageId: item.message_id || '', noteId: ''});
          }
          if (wasEmpty && pending.current.size) setVersion(value => value + 1);
          if (inbox.items.length || pending.current.size) {
            await synchronize(inbox.items);
            const task = await (await request('/task')).json();
            if (!stopped && task.busy && typeof task.turn_id === 'string' && task.turn_id !== completedTurn && inbox.items.some((item: Item) => item.state === 'delivering')) {
              void follow(task.turn_id);
            }
          }
        }
      } catch (error) {if (!stopped) current.current.onError(String(error));}
      if (!stopped) timer = setTimeout(() => void poll(), pending.current.size || following ? 350 : 1000);
    }
    void poll();
    return () => {
      stopped = true; clearTimeout(timer); controller?.abort();
      if (controller && current.current.abortRef.current === controller) {
        current.current.abortRef.current = null;
        current.current.setBusy(false);
      }
    };
  }, [options.config.sessionId, options.config.baseUrl, options.config.demo]);
  const accept = (payload: AcceptedPayload, messageId: string, noteId: string) => {
    if (!payload.queue_id) return;
    const wasEmpty = pending.current.size === 0;
    pending.current.set(payload.queue_id, {messageId: payload.message_id || messageId, noteId});
    if (wasEmpty) setVersion(value => value + 1);
  };
  const resume = async () => {
    const {config} = current.current;
    try {
      await settingsWrites.current;
      const headers: Record<string, string> = {};
      if (config.apiKey) headers.Authorization = `Bearer ${config.apiKey}`;
      const response = await fetch(`${config.baseUrl.replace(/\/$/, '')}/v1/sessions/${encodeURIComponent(config.sessionId)}/inbox/resume`, {method: 'POST', headers});
      const receipt = await response.json();
      if (!response.ok || !Array.isArray(receipt?.items) || receipt?.paused === true) throw new Error(`queue resume failed: HTTP ${response.status}`);
      setPaused(false);
    } catch (error) {current.current.onError(String(error));}
  };
  return {accept, resume, paused};
}
