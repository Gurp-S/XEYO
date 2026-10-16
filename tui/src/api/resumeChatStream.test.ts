import test from 'node:test';
import assert from 'node:assert/strict';
import {streamChat, type ChatBody} from './sse.js';
const body: ChatBody = {session_id: 'resume-test', model: 'local', provider: 'local', stream: true, messages: []};
const frame = (id: number, text: string, turn = 'turn-1') => `data: ${JSON.stringify({xeyo_event_id: id, xeyo_turn_id: turn, choices: [{delta: {content: text}}]})}\n\n`;

for (const mode of ['complete', 'changed', 'crashed', 'race', 'cancel'] as const) {
  test(`disconnected stream: ${mode}`, async () => {
    const original = globalThis.fetch;
    const paths: string[] = [];
    let text = '', error = '', done = 0;
    const ac = new AbortController();
    globalThis.fetch = (async (url: string, init: RequestInit) => {
      paths.push(String(url));
      if (init.method === 'POST') return new Response(frame(1, 'A'));
      if (String(url).endsWith('/task')) return Response.json({turn_id: mode === 'changed' ? 'turn-2' : 'turn-1', status: mode === 'crashed' ? 'recovery_required' : 'running', last_event_id: 2});
      assert.match(String(url), /cursor=1&expected_turn_id=turn-1/);
      return new Response(frame(1, 'A')+frame(2, 'B', mode === 'race' ? 'turn-2' : 'turn-1')+'data: [DONE]\n\n');
    }) as typeof fetch;
    try {
      const running = streamChat('http://fixture', '', body, {onDelta: d => {text += d; if (mode === 'cancel') ac.abort();}, onXy: () => {}, onDone: () => {done++;}, onError: e => {error = e.message;}}, ac.signal);
      await running;
      assert.equal(paths.filter(p => p.endsWith('/completions')).length, 1);
      if (mode === 'complete') {assert.equal(text, 'AB'); assert.equal(done, 1); assert.equal(error, '');}
      else if (mode === 'cancel') {assert.equal(paths.length, 1); assert.equal(done, 1);}
      else {assert.equal(text, 'A'); assert.equal(done, 0); assert.match(error, mode === 'crashed' ? /recovery_required/ : /turn_mismatch/);}
    } finally {globalThis.fetch = original;}
  });
}
