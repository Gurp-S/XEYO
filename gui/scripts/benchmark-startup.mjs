// Production A/B: frozen builds, fresh browser contexts, identical local history,
// fixed CPU throttle, mocked backend; never connects to the user's service/data.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {chromium, expect} from '@playwright/test';

const base = path.resolve(process.env.STARTUP_AB_DIR || '.tmp/startup-ab');
let variant = 'before';
const server = http.createServer((req, res) => {
  const relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).replace(/^\/+/, '');
  const root = path.join(base, variant);
  let file = path.resolve(root, relative || 'index.html');
  if (!file.startsWith(root + path.sep)) {res.writeHead(403); res.end(); return;}
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html');
  const mime = {'.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.json':'application/json', '.woff2':'font/woff2'};
  res.writeHead(200, {'Content-Type':mime[path.extname(file)] || 'application/octet-stream', 'Cache-Control':'no-store'});
  fs.createReadStream(file).pipe(res);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({headless:true});
const rows = [];
const errors = [];
const samples = Number(process.env.STARTUP_SAMPLES || 5);

async function run(name, history) {
  variant = name;
  const context = await browser.newContext({viewport:{width:1280,height:800}});
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', e => errors.push({name,history,message:e.message}));
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (/^\/(v1|api|health)(\/|$)/.test(url.pathname)) return route.fulfill({status:503,json:{detail:'isolated benchmark'}});
    if (url.pathname === '/__seed') return route.fulfill({contentType:'text/html',body:'<!doctype html><title>fixture</title>'});
    if (url.origin !== origin && !['blob:', 'data:'].includes(url.protocol)) return route.abort();
    return route.continue();
  });
  await page.goto(origin + '/__seed');
  await page.evaluate(async history => {
    const request = indexedDB.open('xeyo-web', 5);
    request.onupgradeneeded = () => {
      const db = request.result;
      db.createObjectStore('kv');
      const spaces = db.createObjectStore('spaces',{keyPath:'id'}); spaces.createIndex('by-updated','updatedAt');
      const sessions = db.createObjectStore('sessions',{keyPath:'id'}); sessions.createIndex('by-updated','updatedAt'); sessions.createIndex('by-space','spaceId');
      const messages = db.createObjectStore('messages',{keyPath:['sessionId','id']}); messages.createIndex('by-session','sessionId');
    };
    const db = await new Promise((resolve,reject) => {request.onsuccess=()=>resolve(request.result); request.onerror=()=>reject(request.error);});
    const tx = db.transaction(['kv','spaces','sessions','messages'],'readwrite');
    tx.objectStore('kv').put('complete','__xeyo_migrated__');
    tx.objectStore('spaces').put({id:'space_default',name:'A/B workspace',rootPath:'',createdAt:1,updatedAt:1});
    tx.objectStore('sessions').put({id:'startup-fixture',spaceId:'space_default',title:'启动对照',createdAt:1,updatedAt:1});
    if (history) {
      tx.objectStore('messages').put({sessionId:'startup-fixture',id:'u',role:'user',text:'展示历史记录',createdAt:1});
      tx.objectStore('messages').put({sessionId:'startup-fixture',id:'a',role:'assistant',createdAt:2,
        text:'# 启动验证\n\n**历史正文**与公式：\n\n$$\nE=mc^2\n$$\n\n```javascript\nconst x = 1;\n```\n\n```mermaid\nflowchart LR\n A[输入] --> B[输出]\n```'});
    }
    await new Promise((resolve,reject) => {tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);}); db.close();
  }, history);
  await page.addInitScript(() => {
    window.__startupMeasure = {longTasks:[]};
    new PerformanceObserver(list => {window.__startupMeasure.longTasks.push(...list.getEntries().map(e=>e.duration));}).observe({type:'longtask',buffered:true});
    const observe = new MutationObserver(() => {
      const input = document.querySelector('textarea[aria-label="消息输入"]');
      if (input && !input.disabled && input.getBoundingClientRect().width) {
        window.__startupMeasure.composerMs = performance.now(); observe.disconnect();
      }
    });
    observe.observe(document,{subtree:true,childList:true,attributes:true});
  });
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:4});
  await cdp.send('Performance.enable');
  await page.goto(origin, {waitUntil:'domcontentloaded'});
  await expect(page.getByRole('textbox',{name:'消息输入',exact:true})).toBeEditable();
  let historyReadyMs = null;
  if (history) {
    await expect(page.getByRole('heading',{name:'启动验证',exact:true})).toBeVisible();
    await expect(page.locator('.katex').first()).toBeVisible();
    await expect(page.locator('.xy-code-surface pre .token').first()).toBeVisible();
    await expect(page.getByRole('img',{name:'mermaid',exact:true})).toBeVisible({timeout:15000});
    historyReadyMs = await page.evaluate(()=>performance.now());
  }
  // Include the old idle preloads, rather than measuring only the first paint.
  await page.waitForTimeout(5500);
  const result = await page.evaluate(() => ({...window.__startupMeasure,
    paints:performance.getEntriesByType('paint').map(e=>({name:e.name,ms:e.startTime})),
    resources:performance.getEntriesByType('resource').filter(e=>/\.js(?:\?|$)/.test(e.name)).map(e=>({name:new URL(e.name).pathname,bytes:e.decodedBodySize})),
  }));
  const metrics = (await cdp.send('Performance.getMetrics')).metrics;
  rows.push({variant:name,history,historyReadyMs,...result,jsBytes:result.resources.reduce((n,e)=>n+e.bytes,0),
    scriptMs:1000*metrics.find(m=>m.name==='ScriptDuration').value,taskMs:1000*metrics.find(m=>m.name==='TaskDuration').value});
  await context.close();
  console.log(JSON.stringify({...rows.at(-1),resources:undefined,longTasks:undefined}));
}

try {
  for (const history of [false,true]) for (let i=0;i<samples;i++) {
    for (const name of i%2 ? ['after','before'] : ['before','after']) await run(name,history);
  }
  assert.deepEqual(errors,[]);
} finally {
  fs.writeFileSync(path.join(base,'browser-ab.json'),JSON.stringify({browser:browser.version(),cpuThrottle:4,samples,rows,errors},null,2));
  await browser.close(); await new Promise(resolve=>server.close(resolve));
}
