import {setTimeout as delay} from 'node:timers/promises';
import {consumeChatStream} from './consumeChatStream.js';
import type {SseHandlers} from './sse.js';

class ReplayRejected extends Error {}

/** One POST owns one turn. Transport retries only subscribe to that exact turn. */
export async function consumeResumableChat(options: {
  body: ReadableStream<Uint8Array>; baseUrl: string; sessionId: string;
  headers: Record<string, string>; handlers: SseHandlers; signal?: AbortSignal;
  parse: (line: string) => Record<string, unknown> | null;
  onFrame: (frame: Record<string, unknown>) => void;
}): Promise<void> {
  const {handlers, signal} = options;
  let stream = options.body;
  let turnId = '', cursor = 0, attempts = 0, expectedLast = 0;
  let failure: Error = new Error('incomplete_stream');
  while (true) {
    let done = false;
    await consumeChatStream(stream, {...handlers,
      onDone: () => {done = true;}, onError: e => {failure = e;},
    }, line => {
      const frame = options.parse(line);
      if (!frame) return;
      if (frame.error) throw new ReplayRejected(JSON.stringify(frame.error));
      const xy = (frame.xy ?? frame.xeyo) as Record<string, unknown> | undefined;
      const id = frame.xeyo_turn_id ?? xy?.turn_id;
      const event = frame.xeyo_event_id ?? xy?.event_id;
      if (typeof id === 'string' && id) {
        if (turnId && turnId !== id) throw new ReplayRejected('turn_mismatch: stream belongs to another turn');
        turnId = id;
      }
      if (typeof event === 'number' && Number.isFinite(event) && event > 0 && event <= cursor) return;
      options.onFrame(frame);
      if (typeof event === 'number' && Number.isFinite(event)) cursor = Math.max(cursor, event);
    }, signal);
    if (signal?.aborted) {handlers.onDone(); return;}
    if (done) {
      if (expectedLast > cursor) handlers.onXy({type: 'stream_gap', dropped_through_event_id: expectedLast, first_available_event_id: 0});
      handlers.onDone(); return;
    }
    if (!turnId || failure instanceof ReplayRejected) {handlers.onError(failure); return;}
    let resumed = false;
    while (!resumed && attempts < 5) {
      try {
        await delay(Math.min(2000, 250 * 2 ** attempts++), undefined, {signal});
        const base = `${options.baseUrl.replace(/\/$/, '')}/v1/sessions/${encodeURIComponent(options.sessionId)}`;
        const init = {headers: options.headers, signal};
        const status = await fetch(base+'/task', init);
        if (!status.ok) {
          if (status.status < 500) throw new ReplayRejected(`reattach status: HTTP ${status.status}`);
          throw new Error(`reattach status: HTTP ${status.status}`);
        }
        const task = await status.json() as {turn_id?: string; status?: string; last_event_id?: number};
        if (task.turn_id !== turnId) throw new ReplayRejected('turn_mismatch: current turn changed while disconnected');
        if (task.status === 'recovery_required') throw new ReplayRejected('recovery_required: 服务已重启，本轮执行已中断，等待恢复');
        expectedLast = task.last_event_id ?? 0;
        const q = new URLSearchParams({cursor: String(cursor), expected_turn_id: turnId});
        const response = await fetch(`${base}/turns/current/events?${q}`, init);
        if (!response.ok || !response.body) {
          if (response.status < 500) throw new ReplayRejected(`reattach: HTTP ${response.status}`);
          throw new Error(`reattach: HTTP ${response.status}`);
        }
        stream = response.body;
        resumed = true;
      } catch (e) {
        failure = e instanceof Error ? e : new Error(String(e));
        if (signal?.aborted) {handlers.onDone(); return;}
        if (failure instanceof ReplayRejected) {handlers.onError(failure); return;}
      }
    }
    if (!resumed) {handlers.onError(failure); return;}
  }
}
