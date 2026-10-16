// Offline GUI contracts. Run against a local Vite preview; all backend calls are mocked.
import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const origin=process.env.GUI_REPAIR_URL || 'http://127.0.0.1:5187';
const output=process.env.GUI_REPAIR_OUTPUT || '.tmp/gui-repairs';
fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const evidence={checks:[],errors:[]};
async function check(name,run) {if(process.env.GUI_REPAIR_CASE&&!name.includes(process.env.GUI_REPAIR_CASE))return;try {const detail=await run();evidence.checks.push({name,ok:true,...detail});}catch(error){evidence.checks.push({name,ok:false,error:String(error.stack)});}}
async function boot(path='/bench/chat?rounds=5&bench=1',backend) {
 const p=await browser.newPage({viewport:{width:1280,height:800}});p.setDefaultTimeout(8000);
 p.on('pageerror',error=>evidence.errors.push(error.message));
 p.on('console',message=>{if(message.type()==='error' && /getSnapshot|Rendered (more|fewer) hooks|\[XEYO GUI\]/.test(message.text()))evidence.errors.push(message.text());});
 await p.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(/^\/(v1|api|health)(\/|$)/.test(url.pathname)) {
   if(backend && await backend(route,url))return;
   return route.fulfill({status:503,json:{detail:'Isolated GUI check'}});
  }
  if(url.origin!==origin && !['data:','blob:'].includes(url.protocol))return route.abort();
  return route.continue();
 });
 await p.goto(origin+path,{waitUntil:'domcontentloaded'});
 await p.waitForFunction(()=>!!window.__XEYO_CHAT__);
 if(path.startsWith('/bench'))await p.waitForFunction(()=>!!window.__XY_REPLAY__);
 await p.evaluate(()=>{
  // Vite HMR may retain a timestamp query in the application's module URL.
  // Import that exact instance so fixture writes target the mounted stores.
  window.__repairImport=path=>import(performance.getEntriesByType('resource').find(entry=>new URL(entry.name).pathname===path)?.name ?? path);
 });
 return p;
}
await check('Goal and queue edit, reorder and conflict',async()=>{
 let goal={goal_id:'audit-goal',title:'优化 GUI 交互',text:'优化 GUI 的队列与目标交互\n保留用户输入和消息顺序\n验证多行编辑、保存失败与并发变化',status:'active',pending_complete:false,rounds:1,max_rounds:0,blocked_reason:'',revision:1};
 let items=Array.from({length:3},(_,i)=>({queue_id:'audit-q'+i,text:['检查布局\n保留多行要求','修改 Goal 编辑方式','调整队列顺序'][i],state:'queued',position:i+1,queued_at:Date.now()+i,attempts:0,autorun:false}));
 const writes=[];let goalConflict=false,queueFailure=false,orderConflict=false;
 const p=await boot(undefined,async(r,u)=>{
  const method=r.request().method();const sid=u.pathname.split('/')[3];
  if(u.pathname.endsWith('/goal')) {
   if(method==='PATCH') {const body=r.request().postDataJSON();writes.push({kind:'goal',body});
    if(goalConflict){goal={...goal,text:'其他窗口更新的目标',revision:goal.revision+1};await r.fulfill({status:409,json:{goal}});return true;}
    goal={...goal,text:body.text??goal.text,revision:goal.revision+1};
   }
   await r.fulfill({json:goal});return true;
  }
  if(u.pathname.endsWith('/inbox')&&method==='GET'){await r.fulfill({json:{ok:true,session_id:sid,autorun:false,items}});return true;}
  if(u.pathname.endsWith('/inbox/reorder')){
   const body=r.request().postDataJSON();writes.push({kind:'order',body});
   if(orderConflict){await r.fulfill({status:409,json:{detail:'inbox_order_conflict'}});return true;}
   items=body.order.map((id,index)=>({...items.find(item=>item.queue_id===id),position:index+1}));
   await r.fulfill({json:{ok:true,session_id:sid,order:body.order}});return true;
  }
  if(u.pathname.includes('/inbox/')&&method==='PATCH') {
   const body=r.request().postDataJSON();writes.push({kind:'queue',body});
   if(queueFailure){await r.fulfill({status:503,json:{detail:'offline'}});return true;}
   const item=items.find(item=>item.queue_id===u.pathname.split('/').at(-1));item.text=body.text;
   await r.fulfill({json:{ok:true,item}});return true;
  }
  return false;
 });
 await p.evaluate(({goal,items})=>{const store=window.__XEYO_CHAT__;const id=store.getState().activeId;store.setState({sessionGoalById:{[id]:{goal,driver:null}},inboxBySession:{[id]:items}});},{goal,items});
 if(await p.getByRole('tab',{name:'队列',exact:true}).count())await p.getByRole('tab',{name:'队列',exact:true}).click();
 await p.getByRole('button',{name:/待发送消息/}).click();
 await p.screenshot({path:output+'/docks-after.png'});
 const rows=p.locator('[data-queue-id]');
 assert.equal(await rows.count(),3);assert.equal(await p.locator('.xy-queue-drag[draggable=true]').count(),3);
 await rows.nth(2).getByRole('button',{name:'上移消息'}).click();
 await expect(rows.nth(1)).toHaveAttribute('data-queue-id','audit-q2');
 await p.locator('[data-queue-id="audit-q0"] .xy-queue-drag').dragTo(p.locator('[data-queue-id="audit-q1"]'));
 await expect(rows.nth(2)).toHaveAttribute('data-queue-id','audit-q0');
 orderConflict=true;await rows.nth(0).getByRole('button',{name:'下移消息'}).click();
 await expect(p.getByRole('alert').filter({hasText:'队列已变化'})).toBeVisible();
 await expect(rows.nth(2)).toHaveAttribute('data-queue-id','audit-q0');orderConflict=false;
 if(await p.getByRole('tab',{name:'目标',exact:true}).count())await p.getByRole('tab',{name:'目标',exact:true}).click();
 await p.getByRole('button',{name:'编辑目标',exact:true}).click();
 const editor=p.getByRole('textbox',{name:'目标内容',exact:true});
 assert.equal(await editor.evaluate(el=>el.tagName),'TEXTAREA');await expect(editor).toHaveValue(goal.text);
 await editor.fill('第一行\n第二行');await editor.press('End');await editor.press('Enter');await editor.pressSequentially('第三行');await editor.blur();
 assert.equal(writes.filter(x=>x.kind==='goal').length,0);
 await p.screenshot({path:output+'/goal-edit-after.png'});
 await p.getByRole('button',{name:'保存目标',exact:true}).click();await expect(editor).toHaveCount(0);
 assert.equal(writes.find(x=>x.kind==='goal').body.text,'第一行\n第二行\n第三行');
 if(await p.getByRole('tab',{name:'目标',exact:true}).count())await p.getByRole('tab',{name:'目标',exact:true}).click();
 await p.getByRole('button',{name:'编辑目标',exact:true}).click();await editor.fill('保留我的草稿');goalConflict=true;
 await p.getByRole('button',{name:'保存目标',exact:true}).click();await expect(editor).toHaveValue('保留我的草稿');
 await expect(p.getByText('最新目标',{exact:true})).toBeVisible();assert.equal(writes.filter(x=>x.kind==='goal').length,2);
 await p.getByRole('button',{name:'取消',exact:true}).click();
 if(await p.getByRole('tab',{name:'队列',exact:true}).count())await p.getByRole('tab',{name:'队列',exact:true}).click();
 await p.locator('[data-queue-id="audit-q0"]').getByRole('button',{name:'编辑消息'}).click();
 const queueEditor=p.getByRole('textbox',{name:'编辑排队消息',exact:true});await expect(queueEditor).toHaveValue('检查布局\n保留多行要求');
 await queueEditor.fill('修改后第一行\n修改后第二行');await queueEditor.blur();assert.equal(writes.filter(x=>x.kind==='queue').length,0);
 queueFailure=true;await p.getByRole('button',{name:'保存',exact:true}).click();await expect(p.getByRole('alert')).toContainText('修改未保存');await expect(queueEditor).toHaveValue('修改后第一行\n修改后第二行');
 queueFailure=false;await p.getByRole('button',{name:'保存',exact:true}).click();await expect(queueEditor).toHaveCount(0);
 assert.equal(items.find(item=>item.queue_id==='audit-q0').text,'修改后第一行\n修改后第二行');
 await p.setViewportSize({width:720,height:720});await p.waitForTimeout(400);await p.screenshot({path:output+'/docks-720-after.png'});
 await p.evaluate(async()=>{const {useSettingsStore}=await window.__repairImport('/src/stores/settingsStore.ts');useSettingsStore.getState().update({theme:'graphite'});});
 await p.screenshot({path:output+'/docks-dark-after.png'});
 await p.setViewportSize({width:720,height:480});if(await p.getByRole('tab',{name:'目标',exact:true}).count())await p.getByRole('tab',{name:'目标',exact:true}).click();
 await p.getByRole('button',{name:'编辑目标',exact:true}).click();
 await expect(p.getByRole('button',{name:'保存目标',exact:true})).toBeInViewport({ratio:1});
 await expect(p.getByRole('textbox',{name:'目标内容',exact:true})).toBeInViewport({ratio:1});
 await expect(p.locator('.xy-composer-card textarea')).toBeInViewport({ratio:1});
 await p.screenshot({path:output+'/goal-edit-minimum-after.png'});
 await p.getByRole('button',{name:'取消',exact:true}).click();
 await p.getByRole('tab',{name:'队列',exact:true}).click();
 await p.locator('[data-queue-id="audit-q0"]').getByRole('button',{name:'编辑消息'}).click();
 await queueEditor.fill('消息投递后仍保留这份草稿');
 items=[];
 await p.evaluate(()=>{const store=window.__XEYO_CHAT__;const id=store.getState().activeId;store.setState({inboxBySession:{[id]:[]}});});
 await expect(queueEditor).toBeVisible();
 await p.getByRole('button',{name:'保存',exact:true}).click();
 await expect(p.getByRole('alert')).toContainText('消息已开始投递');
 await p.getByRole('tab',{name:'目标',exact:true}).click();
 await p.getByRole('tab',{name:'队列',exact:true}).click();
 await expect(queueEditor).toHaveValue('消息投递后仍保留这份草稿');
 await p.getByRole('button',{name:'取消',exact:true}).click();
 await expect(p.getByRole('tab',{name:'队列',exact:true})).toHaveCount(0);
 const details={goalEditor:'TEXTAREA',queueEditor:'TEXTAREA',writes,deliveredQueueDraftRetained:true};
 await p.close();return details;
});
await check('Git status, all registered models, command copy',async()=>{
 const p=await boot(undefined,async(r,u)=>{if(!u.pathname.includes('/git/status'))return false;await r.fulfill({json:{ok:true,repo:true,clean:false,branch:'audit',staged:[{path:'added.ts',status:'A'}],unstaged:[{path:'deleted.ts',status:'D'}],untracked:[{path:'untracked.ts',status:'??'}]}});return true;});
 await p.evaluate(()=>{const store=window.__XEYO_CHAT__;store.setState({spaces:store.getState().spaces.map(space=>({...space,rootPath:'D:/audit-fixture'}))});});
 await p.getByRole('tab',{name:'文件',exact:true}).focus();await p.keyboard.press('ArrowRight');
 await expect(p.getByRole('tab',{name:'更改',exact:true})).toBeFocused();await expect(p.getByRole('tab',{name:'更改',exact:true})).toHaveAttribute('aria-selected','true');
 await p.keyboard.press('Home');await expect(p.getByRole('tab',{name:'文件',exact:true})).toBeFocused();
 await p.keyboard.press('End');await expect(p.getByRole('tab',{name:'更改',exact:true})).toBeFocused();await p.getByRole('button',{name:'Git',exact:true}).click();
 await expect(p.locator('.xy-work-change-row')).toHaveCount(3);const git=await p.locator('.xy-work-change-row').allTextContents();
 assert.deepEqual(git,['Aadded.ts','Ddeleted.ts','?untracked.ts']);
 await p.evaluate(async()=>{const {useSettingsStore}=await window.__repairImport('/src/stores/settingsStore.ts');const profile={id:'audit-profile',provider:'openai',name:'审计账号',apiKey:'offline-fixture',baseUrl:'http://127.0.0.1:1/v1',models:Array.from({length:8},(_,i)=>({id:'model-'+(i+1),contextLimit:8000}))};useSettingsStore.setState({profiles:[profile],activeProfileId:profile.id,provider:'openai',model:'model-8',apiKey:profile.apiKey,baseUrl:profile.baseUrl});});
 await p.getByRole('button',{name:/model-8/}).click();await expect(p.getByRole('option')).toHaveCount(8);await expect(p.getByText(/8 个已登记模型/)).toBeVisible();await p.keyboard.press('Escape');
 await p.evaluate(async()=>{window.__XY_REPLAY__.setMessages([{id:'u',role:'user',text:'运行命令',createdAt:1},{id:'tool',role:'tool',toolName:'Bash',toolUseId:'t',toolInput:JSON.stringify({command:'echo hello'}),toolStatus:'success',text:'hello',createdAt:2}]);const {useWorkspaceStore}=await window.__repairImport('/src/stores/workspaceStore.ts');useWorkspaceStore.getState().setActiveTool('history');Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__COPIED=text;}}});});
 await p.getByRole('button',{name:'复制命令',exact:true}).first().click({force:true});assert.equal(await p.evaluate(()=>window.__COPIED),'echo hello');await p.close();return {git,models:8,clipboard:'echo hello'};
});
await check('settings visibility, focus, grouping, and compact sidebar',async()=>{
 const requests=[];const p=await boot(undefined,async(r,u)=>{requests.push(u.pathname);return false;});
 await p.evaluate(()=>window.__XEYO_CHAT__.getState().setSidebarOpen(true));await p.setViewportSize({width:720,height:720});
 await p.waitForFunction(()=>window.__XEYO_CHAT__.getState().sidebarOpen===false);
 await p.evaluate(()=>window.__XEYO_CHAT__.getState().setSidebarOpen(true));await expect(p.getByRole('button',{name:'关闭侧栏',exact:true})).toBeVisible();
 await p.keyboard.press('Escape');await expect(p.getByRole('button',{name:'关闭侧栏',exact:true})).toHaveCount(0);
 requests.length=0;await p.evaluate(async()=>{const {useSettingsStore}=await window.__repairImport('/src/stores/settingsStore.ts');useSettingsStore.getState().openSettings('appearance');});
 await expect(p.getByRole('dialog',{name:'设置',exact:true})).toBeFocused();await p.waitForTimeout(10500);
 const unrelated=requests.filter(path=>/local-models|memory.settings|memory-settings|grants|bash.routing|runtime.preset/.test(path));assert.deepEqual(unrelated,[]);
 await p.getByRole('button',{name:'对话与工具',exact:true}).click();await expect(p.getByRole('spinbutton',{name:/单次对话预算/})).toBeVisible();
 await p.screenshot({path:output+'/settings-behavior-after.png'});await p.getByRole('button',{name:'远程 · 微信',exact:true}).click();await expect(p.getByText('验收：',{exact:false})).toHaveCount(0);
 await p.close();return {hiddenSettingsRequests:unrelated,resizeClosedSidebar:true,settingsFocused:true};
});
await check('extension fetch failure is unknown, not disabled or empty',async()=>{
 const p=await boot('/plugins');await expect(p.getByText(/加载失败/).first()).toBeVisible();
 assert.equal(await p.getByText(/扩展层当前关闭|未安装插件|未配置 MCP/).count(),0);
 await p.screenshot({path:output+'/plugins-failure-after.png'});await p.close();
});
await check('cold empty history and smoothness toggle do not crash',async()=>{
 const p=await boot('/');await p.getByRole('button',{name:'更多工作区工具',exact:true}).click();await p.getByRole('menuitem',{name:'命令记录',exact:true}).click();
 await p.waitForTimeout(250);await p.evaluate(async()=>{const {useSettingsStore}=await window.__repairImport('/src/stores/settingsStore.ts');useSettingsStore.getState().update({smoothness:false});});
 await p.waitForTimeout(250);await expect(p.getByText(/暂时无法显示/)).toHaveCount(0);await p.close();
});
await check('terminal DOM is bounded and directory is paged',async()=>{
 const p=await boot();await p.evaluate(async()=>{const {useWorkspaceStore}=await window.__repairImport('/src/stores/workspaceStore.ts');const {useTerminalSessionStore}=await window.__repairImport('/src/stores/terminalSessionStore.ts');useWorkspaceStore.getState().setActiveTool('terminal');await new Promise(r=>setTimeout(r,100));useTerminalSessionStore.setState({lines:[{kind:'out',text:'log\n'.repeat(200000)}]});});
 await expect(p.getByText(/字符$/).first()).toBeVisible();const chars=await p.locator('.xy-hover-scroll').last().evaluate(el=>el.textContent.length);assert.ok(chars<=24000);
 await p.evaluate(async()=>{const {useExplorerStore}=await window.__repairImport('/src/stores/explorerStore.ts');const {useWorkspaceStore}=await window.__repairImport('/src/stores/workspaceStore.ts');useWorkspaceStore.getState().setActiveTool(null);useWorkspaceStore.getState().setActive('files');await new Promise(r=>setTimeout(r,100));useExplorerStore.setState({childrenByPath:{'':Array.from({length:1000},(_,i)=>({name:`file-${i}.ts`,path:`file-${i}.ts`,kind:'file'}))},error:null,directoryErrors:{}});});
 await expect(p.locator('.xy-work-file-row')).toHaveCount(200);await p.getByRole('button',{name:'下一页',exact:true}).click();await expect(p.locator('.xy-directory-pages')).toContainText('2 / 5');await p.close();return {visibleTerminalChars:chars,visibleDirectoryRows:200};
});
await check('Markdown anchors and worker independent of smoothness',async()=>{
 const p=await boot();await p.evaluate(()=>window.__XY_REPLAY__.setMessages([
  {id:'u1',role:'user',text:'第一份',createdAt:1},{id:'a1',role:'assistant',text:'# 相同标题\n\n第一份正文\n\n[第一份定位](#相同标题)',createdAt:2},
  {id:'u2',role:'user',text:'第二份',createdAt:3},{id:'a2',role:'assistant',text:'# 相同标题\n\n第二份正文\n\n[第二份定位](#相同标题)',createdAt:4},
 ]));
 await expect(p.getByRole('link',{name:'第二份定位'})).toBeVisible();
 const target=await p.evaluate(()=>{const headings=[...document.querySelectorAll('[id="相同标题"]')];let index=-1;const original=Element.prototype.scrollIntoView;Element.prototype.scrollIntoView=function(){index=headings.indexOf(this);};[...document.querySelectorAll('a')].find(a=>a.textContent==='第二份定位').click();Element.prototype.scrollIntoView=original;return index;});
 assert.equal(target,1);
 await p.evaluate(async()=>{window.__XY_REPLAY__.setMessages([{id:'u',role:'user',text:'代码',createdAt:1},{id:'a',role:'assistant',text:'```javascript\nconst x = 1;\n```',createdAt:2}]);const {useSettingsStore}=await window.__repairImport('/src/stores/settingsStore.ts');useSettingsStore.getState().update({smoothness:false});});
 await expect(p.locator('.xy-code-surface pre .token').first()).toBeVisible();await p.close();return {secondHeadingTarget:target,highlightWithSmoothnessOff:true};
});
await browser.close();
fs.writeFileSync(output+'/repair-evidence.json',JSON.stringify(evidence,null,2));
console.log(JSON.stringify(evidence,null,2));
if(evidence.errors.length||evidence.checks.some(check=>!check.ok))process.exitCode=1;
