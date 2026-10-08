/** Actual Ink App with simulated keyboard/transport; no provider or network. */
import React from 'react';
import test from 'node:test';
import {render} from 'ink';
import {PassThrough, Writable} from 'node:stream';
import assert from 'node:assert/strict';
import {App} from './App.js';

const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
const encoder = new TextEncoder();
const originalFetch = globalThis.fetch;

async function scenario(kind: 'retry-clear' | 'retry-load' | 'draft-overwrite') {
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
      if (chatCount === 1 && kind !== 'retry-clear' && kind !== 'retry-load') {
        return new Response(new ReadableStream({start(c) {firstController = c;}}), {status: 200});
      }
      if (chatCount === 2 && kind === 'draft-overwrite') {
        return await new Promise<Response>(resolve => {rejectPending = () => resolve(new Response('rejected', {status: 500}));});
      }
      return new Response('data: {"choices":[{"delta":{"content":"response"}}]}\n\ndata: [DONE]\n\n', {status: 200});
    }
    // This would expose the later queue reply if the App ever requested it.
    return new Response(JSON.stringify({session_id: 'loaded', cwd: 'workspace', messages: []}), {status: 200});
  }) as typeof fetch;
  const instance = render(React.createElement(App, {config: {baseUrl: 'http://offline', apiKey: 'test', provider: 'fake', model: 'fake', cwd: 'workspace', sessionId: 'original', agentMode: 'agent', permissionMode: 'risk', demo: false}}), {stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false, debug: true});
  async function type(text: string, submit = true) {
    stdin.write(text); await delay(75);
    if (submit) {stdin.write('\r'); await delay(150);}
  }
  try {
    await delay(150);
    await type('old task');
    if (kind === 'retry-clear' || kind === 'retry-load') {
      await type(kind === 'retry-clear' ? '/clear' : '/load loaded');
      await type('/retry');
      const chats = requests.filter(r => r.url.endsWith('/v1/chat/completions')).map(r => r.body);
      assert.equal(chats.length, 1, 'retry after a session reset must not submit the previous task');
    } else {
      await type('failed queue task');
      await type('new unsent draft', false);
      output = '';
      rejectPending();
      await delay(200);
      const plain = output.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '');
      assert.equal(plain.includes('new unsent draft'), true, 'late failure overwrote new typing');
      firstController!.enqueue(encoder.encode('data: [DONE]\n\n')); firstController!.close();
      await delay(200); stdin.write('\r'); await delay(200);
      const chats = requests.filter(r => r.url.endsWith('/v1/chat/completions'));
      assert.equal(chats[2].body.messages[0].content, 'new unsent draft');
    }
  } catch (error) {
    process.stderr.write(output.slice(-2500));
    throw error;
  } finally {instance.unmount(); globalThis.fetch = originalFetch;}
}

for (const kind of ['retry-clear', 'retry-load', 'draft-overwrite'] as const) {
  test(kind + ': actual Ink keyboard and transport', async () => {await scenario(kind);});
}
