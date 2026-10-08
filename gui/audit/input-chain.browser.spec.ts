// Observations of existing defects; use audit/input-chain.browser.config.ts.
import {test, expect} from '@playwright/test';
import {bootChat, openWorkspaceSession} from '../e2e/helpers/boot';
import {seedFakeTestSettings} from '../e2e/helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ws = fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-input-observe-'));
const out = path.resolve('..', 'docs', 'input-chain-audit-2026-10-07');

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
  await expect.poll(async () => (await stateOf(page)).inbox.length).toBe(3);
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
  await composer.fill('QUEUED-LIVE-' + 'y'.repeat(1000)); await composer.press('Enter');
  await expect(composer).toHaveValue('');
  await expect.poll(async () => (await stateOf(page)).inbox.some((i: any) => i.state === 'delivering'), {timeout: 20000}).toBe(true);
  await page.waitForTimeout(1000);
  const frontend = await stateOf(page);
  const task = await (await page.request.get(`/v1/sessions/${sid}/task`)).json();
  const stopVisible = await page.getByRole('button', {name: '停止生成'}).first().isVisible().catch(() => false);
  const live = Boolean(frontend.stream?.isLoading || frontend.stream?.remoteStreaming || frontend.stream?.turnDetached);
  const replyStarted = frontend.messages.some((m: any) => m.role === 'assistant' && m.text.includes('QUEUED-LIVE-')) || String(frontend.stream?.streamingText ?? '').includes('QUEUED-LIVE-');
  fs.writeFileSync(path.join(out, 'queue-live-browser.json'), JSON.stringify({task, frontend, stopVisible, live, replyStarted}, null, 2));
  await page.screenshot({path: path.join(out, 'queue-live.png')});
  expect(task.busy).toBe(true);
  // Observation: backend runs, frontend is idle and has no live queued reply.
  expect(live).toBe(false); expect(stopVisible).toBe(false); expect(replyStarted).toBe(false);
});

test('persisted goal is invisible after reload; Composer does not start its reader', async ({page}) => {
  await seedFakeTestSettings(page);
  await bootChat(page);
  const sid = await openWorkspaceSession(page, ws);
  await page.getByLabel('消息输入').fill('/goal persistent goal');
  await page.getByLabel('消息输入').press('Enter');
  await expect(page.locator('[data-goal-bar]')).toBeVisible();
  const requests: string[] = [];
  page.on('request', r => {if (r.url().endsWith('/goal')) requests.push(r.url());});
  await page.reload();
  await expect(page.getByLabel('消息输入')).toBeVisible();
  await page.waitForFunction(() => (window as any).__XEYO_CHAT__?.getState().hydrated);
  await page.waitForTimeout(3500);
  const state = await page.evaluate(() => {
    const s = (window as any).__XEYO_CHAT__.getState();
    return {activeId: s.activeId, goals: s.sessionGoalById};
  });
  const response = await page.request.get(`/v1/sessions/${sid}/goal`);
  const serverGoal = await response.json();
  expect(state.activeId).toBe(sid);
  expect(serverGoal.status).toBe('active');
  await expect(page.locator('[data-goal-bar]')).toHaveCount(0);
  expect(requests).toHaveLength(0);
  fs.writeFileSync(path.join(out, 'goal-reload-browser.json'), JSON.stringify({state, serverGoal, browserGoalRequests: requests}, null, 2));
  await page.screenshot({path: path.join(out, 'goal-reload.png')});
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
  expect(immediate.items.map((i: any) => i.text)).toEqual(['STEER-SELECT-B']);
  await expect.poll(async () => {
    const s = await stateOf(page);
    return s.inbox.length === 0 && s.messages.some((m: any) => m.role === 'assistant' && m.text === 'ok: STEER-SELECT-B');
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
  expect(originalReplies.length).toBeGreaterThan(1);
});
