/** Real Ink App + real HTTP/SSE. Only keyboard/stdout are controlled by this harness. */
import React from 'react';
import {render} from 'ink';
import {PassThrough, Writable} from 'node:stream';
import {readFileSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
import {App} from '../src/app/App.js';

const directory = resolve(process.argv[2]);
const lab = JSON.parse(readFileSync(resolve(directory, 'surfaces.json'), 'utf8'));
const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
async function api(path: string, body?: unknown) {
  const res = await fetch(lab.proxy + path, body === undefined ? {} : {
    method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});
  assert.ok(res.ok, `${path}: ${res.status} ${await res.clone().text()}`);
  return res.json();
}
async function until<T>(get: () => Promise<T> | T, accept: (value: T) => boolean, timeout = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const value = await get(); if (accept(value)) return value;
    await delay(100);
  }
  throw new Error('condition timeout');
}
const windows: Awaited<ReturnType<typeof windowFor>>[] = [];
async function windowFor() {
  const sid = (await api('/v1/sessions', {workspace: lab.workspace})).session_id;
  const stdin = new PassThrough() as any;
  stdin.isTTY = true; stdin.setRawMode = () => {}; stdin.ref = () => {}; stdin.unref = () => {};
  let output = '';
  const stdout = new Writable({write(chunk, _encoding, done) {
    output = (output + chunk.toString()).slice(-2000000); done();
  }}) as any;
  stdout.isTTY = true; stdout.columns = 120; stdout.rows = 40;
  const instance = render(React.createElement(App, {config: {
    baseUrl: lab.proxy, apiKey: '', provider: 'local', model: 'local', cwd: lab.workspace,
    sessionId: sid, agentMode: 'agent', permissionMode: 'never', demo: false,
  }}), {stdin, stdout, stderr: stdout, exitOnCtrlC: false, patchConsole: false, debug: true});
  const key = async (text: string) => {stdin.write(text); await delay(100);};
  return {sid, instance, output: () => output, key,
    type: async (text: string) => {await key(text); await key('\r');},
    task: () => api(`/v1/sessions/${sid}/task`),
    agents: async () => (await api(`/v1/sessions/${sid}/agents`)).agents};
}
const result: Record<string, unknown> = {status: 'running', keyboard: 'controlled Ink streams', transport: 'real HTTP/SSE'};
try {
  for (let i = 0; i < 4; i++) windows.push(await windowFor());
  await delay(200);
  await api('/__test__/fault', {drop_after: 10});
  await Promise.all(windows.map((w, i) => w.type(`XEYO_SOAK inkparallel${i} 2 3`)));
  await Promise.all(windows.map((w, i) => until(w.output, out => out.includes(`PARENT-DONE-inkparallel${i}`))));
  for (let i = 0; i < windows.length; i++) {
    assert.equal((await windows[i].agents()).length, 2);
    for (let j = 0; j < windows.length; j++) if (j !== i) assert.ok(!windows[i].output().includes(`PARENT-DONE-inkparallel${j}`));
  }
  result.concurrent_sessions = 4; result.workers = 8; result.disconnect_recovered = true;
  const w = windows[0];
  await w.type('XEYO_SOAK inkqueuedfirst 2 15');
  await until(w.agents, a => a.some((x: any) => x.desc.includes('inkqueuedfirst')));
  await w.type('XEYO_SOAK inkqueuedsecond 2 1');
  await until(w.output, out => out.includes('消息已排队'));
  await w.key('\x1b');
  await until(w.task, t => !t.busy);
  await until(w.output, out => out.includes('队列已暂停'));
  await w.key('\x12');
  await until(w.output, out => out.includes('PARENT-DONE-inkqueuedsecond'));
  await until(() => api(`/v1/sessions/${w.sid}/inbox`), q => q.items.length === 0);
  result.queue_cancel_resume = true;
  await w.type('XEYO_SOAK inkcrash 2 20');
  await until(w.agents, a => a.filter((x: any) => x.desc.includes('inkcrash')).length === 2);
  const before = (await api('/__test__/requests')).filter((r: any) => r.method === 'POST' && r.path === 'v1/chat/completions').length;
  await api('/__test__/fault', {crash: true, restart: true});
  await until(w.output, out => out.includes('recovery_required'));
  assert.equal((await w.task()).status, 'recovery_required');
  const after = (await api('/__test__/requests')).filter((r: any) => r.method === 'POST' && r.path === 'v1/chat/completions').length;
  assert.equal(after, before, 'crash recovery must not replay POST');
  assert.ok((await w.agents()).filter((a: any) => a.desc.includes('inkcrash')).every((a: any) => a.status !== 'running'));
  result.crash_recovery_notice = true; result.crash_post_replays = after - before;
  result.status = 'passed'; result.sessions = windows.map(w => w.sid);
} catch (error) {
  result.status = 'failed'; result.error = String(error); process.exitCode = 1;
} finally {
  windows.forEach((w, i) => {writeFileSync(resolve(directory, `ink-${i}.log`), w.output()); w.instance.unmount();});
  writeFileSync(resolve(directory, 'ink-result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
}
