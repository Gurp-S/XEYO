/** Actual Ink App with simulated keyboard/transport; no provider or network. */
import React from 'react';
import {render} from 'ink';
import {PassThrough, Writable} from 'node:stream';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {App} from '../src/app/App.js';

const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
const encoder = new TextEncoder();
const observations: unknown[] = [];
const originalFetch = globalThis.fetch;

async function scenario(kind: 'queue-result' | 'retry-clear' | 'draft-overwrite') {
  const stdin = new PassThrough() as any;
  stdin.isTTY = true;
  stdin.setRawMode = () => {};
  stdin.ref = () => {}; stdin.unref = () => {};
  let output = '';
  const stdout = new Writable({write(chunk, _encoding, done) {output += chunk.toString(); done();}}) as any;
  stdout.isTTY = true; stdout.columns = 100; stdout.rows = 35;
  const requests: Array<{url: string; body: any}> = [];
  let firstController: ReadableStreamDefaultController<Uint8Array> | undefined;
  let rejectPending!: () => void;
  let chatCount = 0;
  globalThis.fetch = (async (url: any, options: any = {}) => {
    const target = String(url);
    const body = options.body ? JSON.parse(options.body) : null;
    requests.push({url: target, body});
    if (target.endsWith('/health')) return new Response('{}', {status: 200});
    if (target.endsWith('/v1/sessions') && options.method === 'POST') return new Response(JSON.stringify({ok: true, session_id: 'new-session', cwd: 'workspace'}), {status: 200});
    if (target.endsWith('/v1/chat/completions')) {
      chatCount++;
      if (chatCount === 1 && kind !== 'retry-clear') {
        return new Response(new ReadableStream({start(c) {firstController = c;}}), {status: 200});
      }
      if (chatCount === 2 && kind === 'draft-overwrite') {
        return await new Promise<Response>(resolve => {rejectPending = () => resolve(new Response('rejected', {status: 500}));});
      }
      if (chatCount === 2 && kind === 'queue-result') {
        return new Response(JSON.stringify({queued: true, queue_id: 'q1', position: 1, delivery: 'after_turn'}), {status: 202, headers: {'content-type': 'application/json'}});
      }
      return new Response('data: {"choices":[{"delta":{"content":"response"}}]}\n\ndata: [DONE]\n\n', {status: 200});
    }
    // This would expose the later queue reply if the App ever requested it.
    return new Response(JSON.stringify({session_id: 'original', messages: [{id: 'queued-answer', role: 'assistant', text: 'QUEUE_RESPONSE_MARK'}]}), {status: 200});
  }) as typeof fetch;
  const instance = render(<App config={{baseUrl: 'http://offline', apiKey: 'test', provider: 'fake', model: 'fake', cwd: 'workspace', sessionId: 'original', agentMode: 'agent', permissionMode: 'risk', demo: false}} />, {stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false, debug: true});
  async function type(text: string, submit = true) {
    stdin.write(text); await delay(75);
    if (submit) {stdin.write('\r'); await delay(150);}
  }
  try {
    await delay(150);
    await type('old task');
    if (kind === 'retry-clear') {
      await type('/clear');
      await type('/retry');
      const chats = requests.filter(r => r.url.endsWith('/v1/chat/completions')).map(r => r.body);
      assert.equal(chats.length, 2);
      assert.equal(chats[1].session_id, 'new-session');
      assert.equal(chats[1].messages[0].content, 'old task');
      observations.push({probe: 'tui_retry_after_clear_leaks_old_task', chats});
    } else if (kind === 'queue-result') {
      await type('queued task');
      firstController!.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"first response"}}]}\n\ndata: [DONE]\n\n'));
      firstController!.close();
      await delay(8300); // Includes one full health-poll period.
      const readRequests = requests.filter(r => /inbox|messages|turns/.test(r.url));
      assert.equal(readRequests.length, 0);
      assert.equal(output.includes('QUEUE_RESPONSE_MARK'), false);
      observations.push({probe: 'tui_queue_reply_never_subscribed', chatRequests: chatCount, waitedMs: 8300, readRequests, replyVisible: false});
    } else {
      await type('failed queue task');
      await type('new unsent draft', false);
      output = '';
      rejectPending();
      await delay(200);
      const plain = output.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
      assert.equal(plain.includes('new unsent draft'), false);
      assert.equal(plain.includes('failed queue task'), true);
      observations.push({probe: 'tui_rejected_queue_overwrites_new_draft', newerDraftPreserved: false, originalDraftRestored: true});
      firstController!.enqueue(encoder.encode('data: [DONE]\n\n')); firstController!.close();
    }
  } catch (error) {
    process.stderr.write(output.slice(-2500));
    throw error;
  } finally {instance.unmount(); globalThis.fetch = originalFetch;}
}

await scenario('retry-clear');
await scenario('draft-overwrite');
await scenario('queue-result');
const result = JSON.stringify({mode: 'offline_actual_Ink_App', observations}, null, 2);
fs.writeFileSync(path.resolve('..', 'docs', 'input-chain-audit-2026-10-07', 'tui-observations.json'), result + '\n');
process.stdout.write(result + '\n');
