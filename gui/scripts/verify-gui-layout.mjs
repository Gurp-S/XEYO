// Isolated browser regression checks. Start Vite and set GUI_LAYOUT_URL when using a different port.
// All backend traffic is mocked; models, commands and remote connections are never executed.
import {chromium} from '@playwright/test';
import fs from 'node:fs';
import assert from 'node:assert/strict';

{
const origin=process.env.GUI_LAYOUT_URL || 'http://127.0.0.1:5191';
const out=(process.env.GUI_LAYOUT_OUT || '.tmp/gui-layout-checks')+'/navigation';
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:720,height:480}});
const evidence={errors:[],checks:{}};
page.on('pageerror',e=>evidence.errors.push(e.message));
await page.route('**/*',r=>{
 const u=new URL(r.request().url());
 if(/^\/(v1|api|health)(\/|$)/.test(u.pathname))return r.fulfill({status:503,json:{detail:'Isolated layout audit'}});
 if(u.origin!==origin&&!['data:','blob:'].includes(u.protocol))return r.abort();
 return r.continue();
});
try {
 await page.goto(origin+'/bench/chat?rounds=4&bench=1',{waitUntil:'domcontentloaded',timeout:45000});
 await page.waitForFunction(()=>!!window.__XY_REPLAY__,{},{timeout:45000});
 await page.evaluate(async()=>{
  window.auditImport=path=>import(performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===path)?.name??path);
  window.settings=(await window.auditImport('/src/stores/settingsStore.ts')).useSettingsStore;
  await window.settings.getState().hydrateAsync();window.settings.getState().update({theme:'paper',smoothness:false});
 });
 const nav=page.getByRole('navigation',{name:'应用导航'});
 await nav.getByRole('button',{name:'设置',exact:true}).click();
 evidence.checks.settingsSelected=await nav.getByRole('button',{name:'设置',exact:true}).getAttribute('aria-pressed');
 evidence.checks.chatSelectedUnderSettings=await nav.getByRole('button',{name:'对话',exact:true}).getAttribute('aria-pressed');
 await nav.getByRole('button',{name:'用量',exact:true}).click();await page.getByRole('dialog',{name:'设置',exact:true}).waitFor({state:'hidden'});
 evidence.checks.usageFromSettings={path:new URL(page.url()).pathname,settingsVisible:await page.getByRole('dialog',{name:'设置',exact:true}).isVisible()};
 await page.screenshot({path:out+'/navigation.png'});
 await page.evaluate(()=>window.settings.getState().closeSettings());
 await nav.getByRole('button',{name:'设置',exact:true}).click();
 await nav.getByRole('button',{name:'用量',exact:true}).click();await page.getByRole('dialog',{name:'设置',exact:true}).waitFor({state:'hidden'});
 evidence.checks.samePageFromSettings={path:new URL(page.url()).pathname,settingsVisible:await page.getByRole('dialog',{name:'设置',exact:true}).isVisible()};
 await page.evaluate(()=>window.settings.getState().closeSettings());
 await nav.getByRole('button',{name:'设置',exact:true}).click();await nav.getByRole('button',{name:'对话',exact:true}).click();await page.getByRole('dialog',{name:'设置',exact:true}).waitFor({state:'hidden'});
 evidence.checks.chatFromSettings={path:new URL(page.url()).pathname,settingsVisible:await page.getByRole('dialog',{name:'设置',exact:true}).isVisible()};
 await page.evaluate(()=>window.settings.getState().closeSettings());
 await page.getByRole('button',{name:'选择主题',exact:true}).click();
 const theme=page.locator('.xy-titlebar').getByRole('listbox',{name:'主题',exact:true});
 evidence.checks.theme=await theme.evaluate(el=>{
  const panel=el.parentElement,r=panel.getBoundingClientRect();
  return {total:el.children.length,panelTop:r.top,panelBottom:r.bottom,viewportHeight:innerHeight,overflowY:getComputedStyle(panel).overflowY,clientHeight:panel.clientHeight,scrollHeight:panel.scrollHeight};
 });
 await theme.getByRole('option').last().scrollIntoViewIfNeeded();
 evidence.checks.lastTheme=await theme.getByRole('option').last().evaluate(el=>{const r=el.getBoundingClientRect();return {label:el.getAttribute('aria-label'),top:r.top,bottom:r.bottom,fullyVisible:r.top>=0&&r.bottom<=innerHeight};});
 evidence.checks.titlebarAfterThemeScroll=await page.locator('.xy-titlebar').evaluate(el=>el.getBoundingClientRect().top);
 await page.screenshot({path:out+'/theme.png'});await page.keyboard.press('Escape');
 await page.evaluate(()=>window.settings.getState().openSettings('remote'));await page.waitForTimeout(150);
 evidence.checks.remoteGuide=await page.getByRole('dialog',{name:'设置',exact:true}).innerText();
 await page.screenshot({path:out+'/remote.png'});await page.evaluate(()=>window.settings.getState().closeSettings());
 await page.goto(origin+'/bench/chat?rounds=4&bench=1',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>!!window.__XY_REPLAY__);
 await page.evaluate(async()=>{
  window.auditImport=path=>import(performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===path)?.name??path);
  const s=window.__XEYO_CHAT__;const id=s.getState().activeId;
  const messages=[{id:'u',role:'user',text:'执行命令',createdAt:1},{id:'t',role:'tool',toolName:'Bash',toolUseId:'t',toolInput:JSON.stringify({command:'echo hello'}),toolStatus:'success',text:'hello',createdAt:2}];
  s.setState({messagesById:{...s.getState().messagesById,[id]:messages}});
  const {useWorkspaceStore}=await window.auditImport('/src/stores/workspaceStore.ts');useWorkspaceStore.getState().setOpen(true);useWorkspaceStore.getState().setActiveTool('history');
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>{window.auditCopied=t;}}});
 });
 const copy=page.getByRole('button',{name:'复制命令',exact:true}).first();await copy.click({force:true});await page.waitForTimeout(100);
 evidence.checks.copy={text:await page.evaluate(()=>window.auditCopied),feedback:await copy.innerText()};
 await page.screenshot({path:out+'/copy.png'});
} finally {fs.writeFileSync(out+'/evidence.json',JSON.stringify(evidence,null,2));await browser.close();console.log(JSON.stringify(evidence,null,2));}
assert.deepEqual(evidence.errors,[]);
const checks=evidence.checks;
assert.equal(checks.settingsSelected,'true');assert.equal(checks.chatSelectedUnderSettings,'false');
for(const key of ['usageFromSettings','samePageFromSettings','chatFromSettings'])assert.equal(checks[key].settingsVisible,false,key);
assert.equal(checks.samePageFromSettings.path,'/usage');
assert.ok(checks.theme.panelBottom<=checks.theme.viewportHeight);assert.equal(checks.titlebarAfterThemeScroll,0);
assert.equal(checks.lastTheme.fullyVisible,true);assert.match(checks.remoteGuide,/连接微信/);assert.doesNotMatch(checks.remoteGuide,/顶栏的二维码按钮/);
assert.deepEqual(checks.copy,{text:'echo hello',feedback:'已复制'});

}

{
const origin=process.env.GUI_LAYOUT_URL||'http://127.0.0.1:5191';
const out=(process.env.GUI_LAYOUT_OUT||'.tmp/gui-layout-checks')+'/boundaries';
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:720,height:480}});
page.setDefaultTimeout(7000);
const evidence={errors:[],checks:[]};page.on('pageerror',e=>evidence.errors.push(e.message));
await page.route('**/*',r=>{const u=new URL(r.request().url());if(/^\/(v1|api|health)(\/|$)/.test(u.pathname))return r.fulfill({status:503,json:{detail:'Isolated boundary audit'}});if(u.origin!==origin&&!['data:','blob:'].includes(u.protocol))return r.abort();return r.continue();});
await page.addInitScript(()=>localStorage.setItem('xeyo-settings',JSON.stringify({provider:'openai',model:'audit-model',apiKey:'offline-fixture',baseUrl:'https://example.com/v1',profiles:[{id:'audit',provider:'openai',model:'audit-model',apiKey:'offline-fixture',baseUrl:'https://example.com/v1',name:'界面检查账号',models:[{id:'audit-model',contextLimit:8192},{id:'audit-model-2',contextLimit:8192}]}],activeProfileId:'audit',theme:'paper',smoothness:false})));
async function geometry(locator){return locator.evaluate(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {text:e.textContent?.trim(),x:r.x,y:r.y,width:r.width,height:r.height,withinViewport:r.x>=0&&r.y>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,centerReachable:!!hit&&(hit===e||e.contains(hit))};});}
try{
 await page.goto(origin+'/bench/chat?rounds=4&bench=1',{waitUntil:'domcontentloaded',timeout:45000});await page.waitForFunction(()=>!!window.__XY_REPLAY__,{},{timeout:45000});
 await page.evaluate(async()=>{window.auditImport=p=>import(performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===p)?.name??p);window.settings=(await window.auditImport('/src/stores/settingsStore.ts')).useSettingsStore;await window.settings.getState().hydrateAsync();});
 for(const smoothness of [false,true])for(const kind of ['plan','permission','ask']){
  await page.evaluate(({kind,smoothness})=>{
   window.settings.getState().update({smoothness});const s=window.__XEYO_CHAT__,sessionId=s.getState().activeId;
   s.setState({pendingPlan:kind==='plan'?{requestId:'audit-plan-'+smoothness,sessionId,plan:'检查页面、保留并发修改、验证交互。\n'.repeat(20)}:null,pendingPermission:kind==='permission'?{requestId:'audit-permission-'+smoothness,sessionId,toolName:'Bash',prompt:'echo "只用于布局检查"\n'.repeat(20),reason:'confirm'}:null,pendingAsk:kind==='ask'?{requestId:'audit-ask-'+smoothness,sessionId,question:'优先检查哪个部分？',options:['常用功能','设置和扩展','所有页面'],questions:[]}:null});
  },{kind,smoothness});await page.waitForTimeout(400);
  await page.locator('.xy-panel-ask-body').evaluateAll(es=>es.forEach(e=>e.scrollTop=e.scrollHeight));
  await page.locator('.xy-composer-panels').evaluate(e=>e.scrollTop=e.scrollHeight);await page.waitForTimeout(200);
  const target=kind==='plan'?page.getByRole('button',{name:'允许执行',exact:true}):kind==='permission'?page.getByRole('button',{name:'允许',exact:true}):page.locator('.xy-panel-ask textarea,.xy-panel-ask input').first();
  evidence.checks.push({kind,smoothness,control:await geometry(target),composer:await geometry(page.locator('.xy-composer-card textarea'))});await page.screenshot({path:`${out}/${kind}-${smoothness}.png`});
 }
 await page.evaluate(()=>window.__XEYO_CHAT__.setState({pendingPlan:null,pendingPermission:null,pendingAsk:null}));await page.waitForTimeout(400);
 for(const width of [720,1280]){
  await page.setViewportSize({width,height:width===720?480:800});await page.waitForTimeout(200);
  await page.getByRole('button',{name:/^audit-model/}).click();await page.waitForTimeout(200);
  evidence.checks.push({kind:'model-picker',width,search:await geometry(page.locator('[role=listbox]').locator('..').getByRole('textbox').first()),model:await geometry(page.getByRole('option',{name:'audit-model',exact:true}))});
  await page.screenshot({path:`${out}/model-${width}.png`});
  // Trial click checks clipping and hit testing without changing any model.
  let canSelect=true;try{await page.getByRole('option',{name:'audit-model-2',exact:true}).click({trial:true,timeout:1000});}catch{canSelect=false;}
  evidence.checks.at(-1).canSelect=canSelect;await page.keyboard.press('Escape');
  if(width===720){
   await page.getByRole('button',{name:/^audit-model/}).click();
   await page.getByPlaceholder('搜索模型',{exact:true}).fill('audit-model-2');
   await page.getByRole('option',{name:'audit-model-2',exact:true}).click();
   evidence.checks.push({kind:'model-selection',selected:await page.evaluate(()=>window.settings.getState().model),menuRemainsMounted:await page.getByPlaceholder('搜索模型',{exact:true}).isVisible()});
   await page.keyboard.press('Escape');
  }
 }
 await page.setViewportSize({width:720,height:480});
 await page.evaluate(async()=>{const {useRemoteStore}=await window.auditImport('/src/stores/remoteStore.ts');useRemoteStore.setState({panelOpen:true,state:'error',busy:false,error:'远程服务连接失败，请稍后重试。'.repeat(40)});});await page.waitForTimeout(350);
 evidence.checks.push({kind:'remote-error',close:await geometry(page.getByRole('dialog',{name:'远程启动失败'}).getByRole('button',{name:'关闭',exact:true}))});await page.screenshot({path:out+'/remote.png'});
}finally{fs.writeFileSync(out+'/evidence.json',JSON.stringify(evidence,null,2));await browser.close();console.log(JSON.stringify(evidence,null,2));}
assert.deepEqual(evidence.errors,[]);
for(const check of evidence.checks){
 for(const key of ['control','composer','search','model','close'])if(check[key]){assert.equal(check[key].withinViewport,true,check.kind+' '+key);assert.equal(check[key].centerReachable,true,check.kind+' '+key);}
 if(check.kind==='model-selection')assert.equal(check.selected,'audit-model-2');
 if(check.kind==='model-picker')assert.equal(check.canSelect,true);
}

}

{
const origin=process.env.GUI_LAYOUT_URL||'http://127.0.0.1:5191';
const out=(process.env.GUI_LAYOUT_OUT||'.tmp/gui-layout-checks')+'/usage';fs.mkdirSync(out,{recursive:true});
const fixtures=JSON.parse(fs.readFileSync(new URL('./fixtures/gui-layout.json',import.meta.url),'utf8'));
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:720,height:480}});
await page.route('**/*',r=>{const u=new URL(r.request().url());if(/^\/(v1|api|health)(\/|$)/.test(u.pathname))return r.fulfill({status:fixtures[u.pathname]?200:503,json:fixtures[u.pathname]||{detail:'isolated audit'}});if(u.origin!==origin&&!['data:','blob:'].includes(u.protocol))return r.abort();return r.continue();});
const evidence={};
async function snap(name){await page.waitForTimeout(300);evidence[name]=await page.locator('.xy-a3-report').evaluate(root=>({width:root.clientWidth,scrollWidth:root.scrollWidth,overflows:[...root.querySelectorAll('*')].filter(e=>e.clientWidth>0&&e.scrollWidth>e.clientWidth+3&&getComputedStyle(e).overflowX!=='auto').slice(0,12).map(e=>({tag:e.tagName,cls:e.className,width:e.clientWidth,scroll:e.scrollWidth})),dateSelectVisible:!!root.querySelector('.xy-a3-date-select')?.getClientRects().length}));await page.screenshot({path:out+'/'+name+'.png'});}
try{
 await page.goto(origin+'/usage',{waitUntil:'domcontentloaded',timeout:45000});await page.locator('.xy-a3-dashboard').waitFor();
 for(const width of [720,800,900,1024,1280]){await page.setViewportSize({width,height:width===720?480:800});await snap('final-'+width);}
 for(const [name,value] of Object.entries(evidence)){if(value.scrollWidth>value.width+1)throw new Error(name+' overflow');}

}finally{fs.writeFileSync(out+'/evidence.json',JSON.stringify(evidence,null,2));await browser.close();console.log(JSON.stringify(evidence,null,2));}
}
console.log('GUI layout checks passed');
