// Regression: real browser / real isolated backend, including persisted order.
import {test, expect} from '@playwright/test';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-input-observe-'));
const out = path.resolve('..', 'docs', 'input-chain-audit-2026-10-07', 'fixed');
fs.mkdirSync(out, {recursive: true});

test('direct keyboard steer: pending ownership does not reorder transcript or leave duplicate bubbles', async ({page}) => {
  test.setTimeout(90000);
  await seedFakeTestSettings(page); await bootChat(page);
  const sid = await openWorkspaceSession(page, ws);
  const composer = page.getByLabel('消息输入');
  await composer.fill('DIRECT-FIRST-' + 'x'.repeat(4500)); await composer.press('Enter');
  await expect(page.getByRole('button', {name: '停止生成'}).first()).toBeVisible();
  await composer.fill('DIRECT-STEER-MARK'); await composer.press('Control+Enter');
  await expect(composer).toHaveValue('');
  await expect.poll(async () => {
    const state = await stateOf(page);
    return state.inbox.length === 0 && !state.stream?.isLoading && !state.stream?.draining &&
      state.messages.some((m: any) => m.role === 'assistant' && m.text.includes('DIRECT-STEER-MARK'));
  }, {timeout: 50000}).toBe(true);
  const server = await (await page.request.get(`/v1/sessions/${sid}/messages`)).json();
  const frontend = await stateOf(page);
  const rows = (messages: any[]) => messages.filter(m => !m.uiOnly && !m.isThought).map(({id, role, text}) => ({id, role, text}));
  expect(rows(frontend.messages)).toEqual(rows(server.messages));
  expect(server.messages.filter((m: any) => m.role === 'user' && m.text === 'DIRECT-STEER-MARK')).toHaveLength(1);
  await page.reload();
  await page.waitForFunction(() => (window as any).__XEYO_CHAT__?.getState().hydrated);
  await expect.poll(async () => rows((await stateOf(page)).messages)).toEqual(rows(server.messages));
  fs.writeFileSync(path.join(out, 'direct-steer-browser.json'), JSON.stringify({frontend, server, afterReload: await stateOf(page)}, null, 2));
});

async function stateOf(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const s = (window as any).__XEYO_CHAT__.getState();
    const id = s.activeId;
    return {id, stream: s.sessionStreams[id], inbox: s.inboxBySession[id] ?? [], messages: s.messagesById[id] ?? []};
  });
}

test('queue handoff: compare final browser order and duplicates with backend transcript', async ({page}) => {
  test.setTimeout(90000);
  await seedFakeTestSettings(page);
  await bootChat(page);
  const sid = await openWorkspaceSession(page, ws);
  const composer = page.getByLabel('消息输入');
  const first = 'FIRST-MARK-' + 'x'.repeat(3500);
  const queued = ['QUEUE-A', 'QUEUE-B', 'QUEUE-C'];
  await composer.fill(first); await composer.press('Enter');
  await expect(page.getByRole('button', {name: '停止生成'}).first()).toBeVisible();
  for (const text of queued) {
    await composer.fill(text); await composer.press('Enter');
    await expect(composer).toHaveValue('');
  }
  // A fast delivery can finish before the browser samples the three queue cards.
  // The final comparison below covers all three accepted inputs and both orders.
  const samples: any[] = [];
  for (let i = 0; i < 450; i++) {
    const s = await stateOf(page);
    samples.push({at: i, loading: Boolean(s.stream?.isLoading), draining: Boolean(s.stream?.draining), inbox: s.inbox.map((x: any) => ({text: x.text, state: x.state})), messages: s.messages.map((m: any) => ({id: m.id, role: m.role, text: m.text, queueState: m.queueState}))});
    if (s.inbox.length === 0 && s.messages.some((m: any) => m.role === 'assistant' && m.text.includes('QUEUE-C'))) break;
    await page.waitForTimeout(100);
  }
  await expect.poll(async () => {
    const stream = (await stateOf(page)).stream;
    return !stream?.isLoading && !stream?.draining;
  }, {timeout: 30000}).toBe(true);
  const frontend = await stateOf(page);
  const server = await (await page.request.get(`/v1/sessions/${sid}/messages`)).json();
  const pick = (rows: any[]) => rows.filter(m => ['user', 'assistant'].includes(m.role) && !m.isThought).map(m => ({role: m.role, text: m.text}));
  const actual = pick(frontend.messages), expected = pick(server.messages);
  await page.reload();
  await expect(page.getByLabel('消息输入')).toBeVisible();
  await page.waitForFunction(() => (window as any).__XEYO_CHAT__?.getState().hydrated);
  await page.waitForTimeout(2500);
  const afterReload = pick((await stateOf(page)).messages);
  fs.writeFileSync(path.join(out, `queue-order-${process.env.XEYO_INBOX_COALESCE ?? '1'}.json`), JSON.stringify({actual, expected, afterReload, finalInbox: frontend.inbox, samples}, null, 2));
  await page.screenshot({path: path.join(out, `queue-order-${process.env.XEYO_INBOX_COALESCE ?? '1'}.png`)});
  expect(frontend.inbox).toHaveLength(0);
  expect(actual).toEqual(expected);
  expect(afterReload).toEqual(expected);
  expect(new Set(frontend.messages.map((m: any) => m.id)).size).toBe(frontend.messages.length);
});

test('queue handoff: inspect UI while automatically delivered reply is still running', async ({page}) => {
  test.setTimeout(90000);
  await seedFakeTestSettings(page);
  await bootChat(page);
  const sid = await openWorkspaceSession(page, ws);
  const composer = page.getByLabel('消息输入');
  await composer.fill('FIRST-LIVE-' + 'x'.repeat(400)); await composer.press('Enter');
  await expect(page.getByRole('button', {name: '停止生成'}).first()).toBeVisible();
  await composer.fill('QUEUED-LIVE-' + 'y'.repeat(1900)); await composer.press('Enter');
  await expect(composer).toHaveValue('');
  // The delivery receipt can remove the card between samples. Observe the
  // queued reply itself, then require a live backend and visible stop control.
  await expect.poll(async () => {
    const s = await stateOf(page);
    return String(s.stream?.streamingText ?? '').includes('QUEUED-LIVE-') || s.messages.some((m: any) => m.role === 'assistant' && m.text.includes('QUEUED-LIVE-'));
  }, {timeout: 20000}).toBe(true);
  const frontend = await stateOf(page);
  const task = await (await page.request.get(`/v1/sessions/${sid}/task`)).json();
  const stopVisible = await page.getByRole('button', {name: '停止生成'}).first().isVisible().catch(() => false);
  const live = Boolean(frontend.stream?.isLoading || frontend.stream?.remoteStreaming || frontend.stream?.turnDetached);
  const replyStarted = frontend.messages.some((m: any) => m.role === 'assistant' && m.text.includes('QUEUED-LIVE-')) || String(frontend.stream?.streamingText ?? '').includes('QUEUED-LIVE-');
  fs.writeFileSync(path.join(out, 'queue-live-browser.json'), JSON.stringify({task, frontend, stopVisible, live, replyStarted}, null, 2));
  await page.screenshot({path: path.join(out, 'queue-live.png')});
  expect(task.busy).toBe(true);
  // Backend execution must have a visible stream and a stop control.
  expect(live).toBe(true); expect(stopVisible).toBe(true); expect(replyStarted).toBe(true);
});

test('selected queued steer: inspect lost siblings and transcript duplication after fallback', async ({page}) => {
  test.setTimeout(90000);
  await seedFakeTestSettings(page);
  await bootChat(page);
  const sid = await openWorkspaceSession(page, ws);
  const composer = page.getByLabel('消息输入');
  await composer.fill('FIRST-STEER-' + 'x'.repeat(4500)); await composer.press('Enter');
  await expect(page.getByRole('button', {name: '停止生成'}).first()).toBeVisible();
  for (const text of ['STEER-SIBLING-A', 'STEER-SELECT-B', 'STEER-SIBLING-C']) {
    await composer.fill(text); await composer.press('Enter');
    await expect(composer).toHaveValue('');
  }
  await expect.poll(async () => (await stateOf(page)).inbox.length).toBe(3);
  // Exercise the queue action endpoint directly to keep the busy window stable;
  // message entry, delivery, projection and final transcript use the real app.
  const selected = (await stateOf(page)).inbox.find((i: any) => i.text === 'STEER-SELECT-B');
  const steered = await page.request.post(`/v1/sessions/${sid}/inbox/${selected.queue_id}/steer`);
  expect(steered.ok()).toBe(true);
  const immediate = await (await page.request.get(`/v1/sessions/${sid}/inbox`)).json();
  expect(immediate.items.map((i: any) => i.text)).toEqual(['STEER-SIBLING-A', 'STEER-SELECT-B', 'STEER-SIBLING-C']);
  await expect.poll(async () => {
    const s = await stateOf(page);
    return s.inbox.length === 0 && s.messages.some((m: any) => m.role === 'assistant' && m.text.includes('STEER-SELECT-B'));
  }, {timeout: 50000}).toBe(true);
  await expect.poll(async () => {
    const stream = (await stateOf(page)).stream;
    return !stream?.isLoading && !stream?.draining;
  }, {timeout: 30000}).toBe(true);
  const frontend = await stateOf(page);
  const server = await (await page.request.get(`/v1/sessions/${sid}/messages`)).json();
  const originalReplies = frontend.messages.filter((m: any) => m.role === 'assistant' && m.text.startsWith('ok: FIRST-STEER-'));
  await page.reload();
  await page.waitForFunction(() => (window as any).__XEYO_CHAT__?.getState().hydrated);
  await page.waitForTimeout(2500);
  const afterReload = await stateOf(page);
  fs.writeFileSync(path.join(out, 'selected-steer-browser.json'), JSON.stringify({immediate, frontend, server, afterReload, originalReplyCount: originalReplies.length}, null, 2));
  await page.screenshot({path: path.join(out, 'selected-steer-browser.png')});
  expect(originalReplies.length).toBe(1);
  const roles = (messages: any[]) => messages.filter(m => !m.uiOnly && !m.isThought).map(({role, text}) => ({role, text}));
  expect(roles(frontend.messages)).toEqual(roles(server.messages));
  expect(roles(afterReload.messages)).toEqual(roles(server.messages));
});
