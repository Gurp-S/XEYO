import React from 'react';
import test from 'node:test';
import {render} from 'ink';
import {PassThrough, Writable} from 'node:stream';
import assert from 'node:assert/strict';
import {App} from './App.js';

async function queueScenario(hold: boolean, recover = false, reconnect = false) {
  const originalFetch = globalThis.fetch;
  const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
  const stdin = new PassThrough() as any;
  stdin.isTTY = true; stdin.setRawMode = () => {}; stdin.ref = () => {}; stdin.unref = () => {};
  let output = '';
  const stdout = new Writable({write(chunk, _encoding, done) {output += chunk.toString(); done();}}) as any;
  stdout.isTTY = true; stdout.columns = 100; stdout.rows = 35;
  const encoder = new TextEncoder();
  let native!: ReadableStreamDefaultController<Uint8Array>;
  let automatic!: ReadableStreamDefaultController<Uint8Array>;
  let held = false; const settingsBodies: any[] = [];
  let calls = 0; let queuedId = recover ? 'recovered-user' : ''; let firstId = recover ? 'first-user' : ''; let delivered = false; let acked = false;
  let follows = 0;
  const requests: string[] = [];
  globalThis.fetch = (async (url: any, init: any = {}) => {
    const target = String(url); requests.push(target);
    if (target.endsWith('/health')) return new Response('{}');
    if (target.endsWith('/v1/chat/completions')) {
      const body = JSON.parse(init.body); calls++;
      if (calls === 1) {
        firstId = body.messages[0].id;
        return new Response(new ReadableStream({start(c) {native = c;}}));
      }
      queuedId = body.messages[0].id;
      return new Response(JSON.stringify({queued: true, queue_id: 'q', message_id: queuedId, position: 1}), {status: 202, headers: {'Content-Type': 'application/json'}});
    }
    if (target.endsWith('/inbox')) return Response.json({paused: held, items: acked || (!recover && calls < 2) ? [] : [{queue_id: 'q', message_id: queuedId, delivery_id: queuedId, state: held ? 'queued' : delivered ? 'delivered' : 'delivering'}]});
    if (target.endsWith('/task')) return Response.json({busy: !delivered && !held, turn_id: 'automatic-turn'});
    if (target.endsWith('/messages')) return Response.json({session_id: 'session', cwd: 'workspace', messages: [
      {id: firstId, role: 'user', text: 'first', createdAt: 1},
      {id: 'first-reply', role: 'assistant', text: 'first response', createdAt: 2},
      {id: queuedId, role: 'user', text: 'queued', createdAt: 3},
      ...(delivered ? [{id: 'queued-reply', role: 'assistant', text: 'automatic live response', createdAt: 4}] : []),
    ]});
    if (target.includes('/turns/current/events')) {follows++; return new Response(new ReadableStream({start(c) {automatic = c;}}));}
    if (target.endsWith('/inbox/ack')) {acked = true; return Response.json({ok: true});}
    if (target.endsWith('/request-environment')) {settingsBodies.push(JSON.parse(init.body)); return Response.json({ok: true, session_id: 'session'});}
    if (target.endsWith('/v1/interrupt')) {held = true; native.enqueue(encoder.encode('data: [DONE]\n\n')); native.close(); return Response.json({ok: true});}
    if (target.endsWith('/inbox/resume')) {held = false; return Response.json({paused: false, items: [{queue_id: 'q', state: 'queued'}]});}
    return Response.json({ok: true});
  }) as typeof fetch;
  const instance = render(React.createElement(App, {config: {baseUrl: 'http://offline', apiKey: 'test', provider: 'fake', model: 'fake', cwd: 'workspace', sessionId: 'session', agentMode: 'agent', permissionMode: 'risk', demo: false}}), {stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false, debug: true});
  async function until(check: () => boolean) {for (let i = 0; i < 60 && !check(); i++) await delay(50); assert.ok(check());}
  async function type(text: string) {stdin.write(text); await delay(80); stdin.write('\r'); await delay(150);}
  try {
    if (!recover) {await delay(150); await type('first'); await type('queued');}
    if (hold) {
      stdin.write('\x1b');
      await until(() => output.includes('队列已暂停'));
      assert.equal(Boolean(automatic), false, 'reads must not restart a stopped queue');
      await type('/model fake-latest');
      await until(() => settingsBodies.at(-1)?.model === 'fake-latest');
      stdin.write('\x12');
    } else if (!recover) {
    native.enqueue(encoder.encode('data: {"xeyo_message_id":"first-reply","choices":[{"delta":{"content":"first response"}}]}\n\ndata: [DONE]\n\n')); native.close();
    }
    await until(() => Boolean(automatic));
    automatic.enqueue(encoder.encode('data: {"xeyo_turn_id":"automatic-turn","xeyo_event_id":1,"xeyo_message_id":"queued-reply","choices":[{"delta":{"content":"automatic live response"}}]}\n\ndata: {"xy":{"type":"ask_user_pending","event_id":2,"turn_id":"automatic-turn","request_id":"ask-queue","question":"queued question","options":["yes","no"]}}\n\n'));
    await until(() => output.includes('automatic live response') && output.includes('queued question'));
    stdin.write('1'); await delay(100);
    assert.ok(requests.some(url => url.endsWith('/v1/ask/resolve')));
    if (reconnect) {
      automatic.error(new Error('connection lost'));
      await until(() => follows === 2);
      assert.ok(requests.some(url => url.endsWith('/turns/current/events?cursor=2')), 'resume from the last consumed event in this turn');
      automatic.enqueue(encoder.encode('data: {"xeyo_event_id":1,"xeyo_turn_id":"automatic-turn","xeyo_message_id":"queued-reply","choices":[{"delta":{"content":"DUPLICATE"}}]}\n\ndata: {"xy":{"type":"ask_user_pending","event_id":2,"turn_id":"automatic-turn","request_id":"ask-queue","question":"DUPLICATE QUESTION","options":["yes","no"]}}\n\ndata: {"xeyo_event_id":3,"xeyo_turn_id":"automatic-turn","xeyo_message_id":"queued-reply","choices":[{"delta":{"content":" continued"}}]}\n\n'));
      await until(() => output.includes('automatic live response continued'));
      assert.equal(output.includes('DUPLICATE'), false, 'replayed text and dialogs must not appear again');
    }
    delivered = true;
    automatic.enqueue(encoder.encode('data: [DONE]\n\n')); automatic.close();
    await until(() => acked);
    assert.equal(calls, recover ? 0 : 2, 'following a queued turn must not resubmit a prompt');
  } finally {instance.unmount(); globalThis.fetch = originalFetch;}
}

test('actual Ink recovers a durable queue on startup and resumes a broken stream', async () => queueScenario(false, true, true));

for (const hold of [false, true]) {
  test(`actual Ink queue handoff (${hold ? 'stop, model switch and manual continue' : 'automatic'})`, async () => queueScenario(hold));
}
