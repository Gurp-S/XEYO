// Production frontend with Tauri IPC mocks: no real process, model or user data.
import {chromium, expect} from '@playwright/test';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const origin = process.env.STARTUP_URL || 'http://127.0.0.1:5188';
const mocks = fs.readFileSync('node_modules/@tauri-apps/api/mocks.js','utf8').replace(/^export .*$/gm,'');
const browser = await chromium.launch({headless:true});
const checks = [], errors = [];
async function boot(fail = false) {
  const page = await browser.newPage();
  const requests = [];
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript({content:mocks + `
    window.__nativeCalls=[]; window.__nativeReady=false;
    mockIPC(async (cmd,args) => {
      window.__nativeCalls.push({cmd,at:performance.now()});
      if(cmd==='backend_startup_ready') {
        if(${fail}) throw new Error('isolated startup failure');
        return window.__nativeReady;
      }
      if(cmd==='get_backend_port') return 8877;
      if(cmd==='plugin:window|close') window.dispatchEvent(new Event('pagehide'));
      if(cmd==='plugin:window|is_maximized') return false;
      return null;
    },{shouldMockEvents:true});
    mockWindows('main');
  `});
  await page.route('**/*',route=>{
    const u=new URL(route.request().url());
    if(/^\/(v1|api|health)(\/|$)/.test(u.pathname)) {requests.push(u.href);return route.fulfill({status:503,json:{detail:'isolated startup test'}});}
    if(u.origin!==origin && !['blob:','data:'].includes(u.protocol)) return route.abort();
    return route.continue();
  });
  await page.goto(origin);
  return {page,requests};
}
try {
  const {page,requests}=await boot();
  await expect(page.getByRole('status')).toHaveText('正在启动服务…');
  await page.waitForTimeout(1200);
  assert.equal(requests.length,0,'hydration must not request the not-yet-ready backend');
  await expect(page.getByRole('textbox',{name:'消息输入',exact:true})).toHaveCount(0);
  assert.ok(await page.evaluate(()=>window.__nativeCalls.some(c=>c.cmd==='plugin:window|show')));
  await page.evaluate(()=>{window.__nativeReady=true;});
  await expect(page.getByRole('textbox',{name:'消息输入',exact:true})).toBeEditable();
  assert.ok(requests.length>0); assert.ok(requests.every(url=>new URL(url).port==='8877'));
  checks.push({case:'visible shell before backend; hydrate only after ready; migrated port before first request',passed:true});
  await page.close();

  const closing=await boot();
  await expect(closing.page.getByRole('status')).toHaveText('正在启动服务…');
  await closing.page.getByRole('button',{name:'关闭',exact:true}).click();
  const count=await closing.page.evaluate(()=>window.__nativeCalls.filter(c=>c.cmd==='backend_startup_ready').length);
  await closing.page.waitForTimeout(450);
  assert.equal(await closing.page.evaluate(()=>window.__nativeCalls.filter(c=>c.cmd==='backend_startup_ready').length),count);
  assert.equal(closing.requests.length,0); checks.push({case:'close cancels readiness polling',passed:true});
  await closing.page.close();

  const failure=await boot(true);
  await expect(failure.page.getByRole('status')).toContainText('isolated startup failure');
  await expect(failure.page.getByRole('button',{name:'重新加载'})).toBeVisible();
  await failure.page.getByRole('button',{name:'查看本地对话'}).click();
  await expect(failure.page.getByRole('textbox',{name:'消息输入',exact:true})).toBeEditable();
  checks.push({case:'failure remains visible and permits local history',passed:true});
  await failure.page.close();
  assert.deepEqual(errors,[]);
} finally {
  await browser.close();
  fs.writeFileSync('.tmp/startup-ab/native-frontend-contracts.json',JSON.stringify({checks,errors},null,2));
  console.log(JSON.stringify({checks,errors},null,2));
}
