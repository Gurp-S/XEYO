import {test, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import {bootChat, openWorkspaceSession} from '../e2e/helpers/boot';
import {seedLocalTest} from '../e2e/helpers/seed';
const lab = JSON.parse(fs.readFileSync(process.env.XEYO_SOAK_LAB || '../.tmp/multiagent-soak-20261015/surfaces/surfaces.json', 'utf8'));
async function setup(page: Page) {
  await seedLocalTest(page, {baseUrl: lab.model_base, permissionMode: 'never'});
  await bootChat(page);
  return openWorkspaceSession(page, lab.workspace);
}
async function send(page: Page, text: string) {
  await page.getByLabel('消息输入').fill(text);
  await page.getByLabel('消息输入').press('Enter');
}
async function cards(page: Page, sid: string) {
  return (await (await page.request.get(`${lab.proxy}/v1/sessions/${sid}/agents`)).json()).agents;
}

test('two real browser sessions: disconnect/reload, cancel/retry and agent mail', async ({browser}) => {
  const contexts = await Promise.all([browser.newContext(), browser.newContext()]);
  const pages = await Promise.all(contexts.map(c => c.newPage()));
  try {
    const sids = await Promise.all(pages.map(setup));
    await pages[0].request.post(lab.proxy+'/__test__/fault', {data: {drop_after: 10}});
    await Promise.all(pages.map((p, n) => send(p, `XEYO_SOAK gui${n} 2 8`)));
    await Promise.all(pages.map((p, n) => expect.poll(async () => (await cards(p, sids[n])).length).toBe(2)));
    const initial = await cards(pages[1], sids[1]);
    await pages[1].getByRole('button', {name: /^取消 /}).first().click();
    await pages[0].reload();
    await expect(pages[0].getByText(/PARENT-DONE-gui0/).first()).toBeVisible({timeout: 30000});
    await expect(pages[1].getByText(/PARENT-DONE-gui1/).first()).toBeVisible({timeout: 30000});
    await pages[1].getByRole('button', {name: /^重试 /}).first().click();
    await expect.poll(async () => (await cards(pages[1], sids[1])).every((a: any) => a.runtimeState === 'completed'), {timeout: 30000}).toBe(true);
    expect((await cards(pages[1], sids[1])).some((a: any) => !initial.some((b: any) => b.attemptId === a.attemptId))).toBe(true);
    await pages[0].locator('.xy-agent-bar-main').first().click();
    const follow = pages[0].getByPlaceholder(/追加信息/);
    await follow.fill('MAIL-gui-follow');
    await follow.press('Enter');
    await expect.poll(async () => (await cards(pages[0], sids[0])).reduce((n: number, a: any) => n+a.inboxCount, 0)).toBe(1);
    await pages[0].getByRole('button', {name: '上一个界面', exact: true}).click();
    await pages[0].getByRole('button', {name: /^继续 XEYO_WORKER/}).click({timeout: 10000});
    await expect.poll(async () => (await cards(pages[0], sids[0])).every((a: any) => a.runtimeState === 'completed' && a.inboxCount === 0), {timeout: 30000}).toBe(true);
    await expect(pages[0].getByRole('button', {name: /^继续 XEYO_WORKER/})).toHaveCount(0);
    await pages[0].screenshot({path: '../.tmp/multiagent-soak-20261015/gui-agent.png'});
  } finally {await Promise.all(contexts.map(c => c.close()));}
});

test('browser crash recovery is explicit and parent stop releases busy', async ({page}) => {
  const sid = await setup(page);
  await send(page, 'XEYO_SOAK guicrash 2 20');
  await expect.poll(async () => (await cards(page, sid)).length).toBe(2);
  await page.request.post(lab.proxy+'/__test__/fault', {data: {crash: true}});
  await page.request.post(lab.proxy+'/__test__/fault', {data: {restart: true}});
  await page.reload();
  await expect.poll(async () => (await (await page.request.get(lab.proxy+`/v1/sessions/${sid}/task`)).json()).status).toBe('recovery_required');
  await expect(page.getByText(/上次任务在重启前未完成/)).toBeVisible();
  await page.screenshot({path: '../.tmp/multiagent-soak-20261015/gui-recovery.png'});
  const sid2 = await openWorkspaceSession(page, lab.workspace);
  await send(page, 'XEYO_SOAK guistop 2 20');
  await expect.poll(async () => (await cards(page, sid2)).length).toBe(2);
  const stopReceipt = page.waitForResponse(r => r.url().endsWith('/v1/interrupt'));
  await page.getByRole('button', {name: '停止生成', exact: true}).click();
  const stopped = await stopReceipt;
  console.log('STOP_RECEIPT', stopped.status(), await stopped.text());
  await expect.poll(async () => (await (await page.request.get(lab.proxy+`/v1/sessions/${sid2}/task`)).json()).busy).toBe(false);
});
