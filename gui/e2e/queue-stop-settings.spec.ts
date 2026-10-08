import {test, expect} from '@playwright/test';
import {bootChat, openWorkspaceSession} from './helpers/boot';
import {seedFakeTestSettings} from './helpers/seed';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

test('stop holds queue through reload; manual continue executes with latest model settings', async ({page}) => {
  test.setTimeout(90000);
  await seedFakeTestSettings(page); await bootChat(page);
  const sid = await openWorkspaceSession(page, fs.mkdtempSync(path.join(os.tmpdir(), 'xeyo-stop-settings-')));
  const composer = page.getByLabel('消息输入');
  await composer.fill('STOP-FIRST-' + 'x'.repeat(6500)); await composer.press('Enter');
  await expect(page.getByRole('button', {name: '停止生成'}).first()).toBeVisible();
  await composer.fill('AFTER-MANUAL-CONTINUE'); await composer.press('Enter');
  await expect(composer).toHaveValue('');
  await page.getByRole('button', {name: '停止生成'}).first().click();
  await expect.poll(async () => (await (await page.request.get(`/v1/sessions/${sid}/task`)).json()).busy).toBe(false);
  await page.reload();
  await expect(page.getByRole('button', {name: '继续投递', exact: true})).toBeVisible();
  await page.waitForTimeout(2200);
  const held = await (await page.request.get(`/v1/sessions/${sid}/inbox`)).json();
  expect(held.paused).toBe(true); expect(held.items[0].text).toBe('AFTER-MANUAL-CONTINUE');
  expect((await (await page.request.get(`/v1/sessions/${sid}/task`)).json()).busy).toBe(false);
  const settingsReceipt = page.waitForResponse(response => response.url().endsWith(`/v1/sessions/${sid}/request-environment`) && response.request().postDataJSON()?.model === 'fake-latest');
  await page.evaluate(async () => {
    const modulePath = '/src/stores/settingsStore.ts';
    const {useSettingsStore} = await import(modulePath);
    useSettingsStore.getState().update({model: 'fake-latest', outputCompact: true, outputMode: 'ultra'});
  });
  expect((await settingsReceipt).ok()).toBe(true);
  await page.getByRole('button', {name: '继续投递', exact: true}).click();
  await expect.poll(async () => (await (await page.request.get(`/v1/sessions/${sid}/task`)).json()).model, {timeout: 20000}).toBe('fake-latest');
  await expect.poll(async () => {
    const messages = (await (await page.request.get(`/v1/sessions/${sid}/messages`)).json()).messages;
    return messages.some((message: any) => message.role === 'assistant' && message.text.includes('AFTER-MANUAL-CONTINUE'));
  }, {timeout: 30000}).toBe(true);
  await expect(page.getByRole('button', {name: '继续投递', exact: true})).toHaveCount(0);
});
