import {chromium} from '@playwright/test';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const origin=process.env.GUI_SCOPE_URL||'http://127.0.0.1:5195',out=process.env.GUI_SCOPE_OUT||'.tmp/gui-scope-checks';
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:720,height:480}});page.setDefaultTimeout(10000);
const result={errors:[],checks:[],requests:[]};page.on('pageerror',e=>result.errors.push(e.message));
const fixtures=JSON.parse(fs.readFileSync('scripts/fixtures/gui-layout.json','utf8'));
let configRev='a'.repeat(64),configData={servers:{}};
await page.route('**/*',async r=>{
 const u=new URL(r.request().url()),p=u.pathname;
 if(/^\/(v1|api|health)(\/|$)/.test(p)){
  if(p==='/v1/extensions/configuration'){
   if(r.request().method()==='GET')return r.fulfill({json:{ok:true,scope:u.searchParams.get('scope'),kind:u.searchParams.get('kind'),path:'C:/layout-fixture/.xeyo/'+(u.searchParams.get('kind')==='mcp'?'mcp.json':'settings.json'),revision:configRev,data:u.searchParams.get('kind')==='mcp'?configData:{enabled_extensions:false}}});
   const data=r.request().postDataJSON();result.requests.push({path:p,...data});
   if(data.revision!==configRev)return r.fulfill({status:409,json:{detail:'configuration changed'}});
   if(data.kind==='mcp'&&(!data.data.servers||Object.values(data.data.servers).some(s=>!s.command)))return r.fulfill({status:422,json:{detail:'command is required'}});
   if(!data.validate_only){configRev='b'.repeat(64);configData=data.data;}
   return r.fulfill({json:{ok:true,validated:true,saved:!data.validate_only,revision:configRev}});
  }
  if(p==='/v1/models'){result.requests.push({path:p,provider:r.request().headers()['x-provider'],baseUrl:r.request().headers()['x-base-url']});return r.fulfill({json:{vendor_ok:true,data:[{id:'model-candidate',context_length:8192}]}});}
  if(p.includes('vendor')&&r.request().method()==='POST'){result.requests.push({path:p,...r.request().postDataJSON()});return r.fulfill({json:{vendor_ok:true,data:[{id:'model-candidate',context_length:8192}]}});}
  if(fixtures[p])return r.fulfill({json:fixtures[p]});
  return r.fulfill({status:503,json:{detail:'isolated GUI comparison'}});
 }
 if(u.origin!==origin&&!['data:','blob:'].includes(u.protocol))return r.abort();return r.continue();
});
await page.addInitScript(theme=>localStorage.setItem('xeyo-settings',JSON.stringify({provider:'openai',model:'audit-model',apiKey:'offline-fixture',baseUrl:'https://example.com/v1',profiles:[{id:'audit',provider:'openai',model:'audit-model',apiKey:'offline-fixture',baseUrl:'https://example.com/v1',name:'界面检查账号',models:[{id:'audit-model',contextLimit:8192}]}],activeProfileId:'audit',theme,smoothness:false,showExperimental:true,rewindGcMaxBytes:104857600})),process.env.GUI_SCOPE_THEME||'paper');
async function geometry(locator){if(!await locator.count())return null;return locator.first().evaluate(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,reachable:!!hit&&(hit===e||e.contains(hit)),font:getComputedStyle(e).fontSize};});}
async function shot(name){await page.screenshot({path:`${out}/${name}.png`});}
async function settings(tab){await page.evaluate(t=>window.settings.getState().openSettings(t),tab);await page.getByRole('dialog',{name:'设置',exact:true}).waitFor();}
async function closeSettings(){await page.evaluate(()=>window.settings.getState().closeSettings());await page.getByRole('dialog',{name:'设置',exact:true}).waitFor({state:'hidden'});}
try{
 await page.goto(origin+'/bench/chat?rounds=20&bench=1',{waitUntil:'domcontentloaded',timeout:60000});await page.waitForFunction(()=>!!window.__XY_REPLAY__,{},{timeout:60000});
 await page.evaluate(async()=>{window.auditImport=p=>import(performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===p)?.name??p);window.settings=(await window.auditImport('/src/stores/settingsStore.ts')).useSettingsStore;await window.settings.getState().hydrateAsync();window.ws=(await window.auditImport('/src/stores/workspaceStore.ts')).useWorkspaceStore;});
 result.checks.push({kind:'initial-workspace',open:await page.evaluate(()=>window.ws.getState().open)});
 for(const width of [720,1280])for(const tool of ['browser','terminal','map']){
  await page.setViewportSize({width,height:width===720?480:800});
  await page.evaluate(tool=>{window.ws.getState().setOpen(true);window.ws.getState().setActiveTool(tool);},tool);await page.waitForTimeout(300);
  result.checks.push({kind:'tool',tool,width,pane:await geometry(page.locator('.xy-review-workbench')),input:await geometry(page.locator('.xy-composer-card textarea')),address:tool==='browser'?await geometry(page.getByRole('textbox',{name:'预览地址',exact:true})):null});await shot(`${tool}-${width}`);
  if(tool==='terminal'&&width===1280){await page.getByRole('separator',{name:'调整工作区宽度'}).press('ArrowLeft');await page.waitForTimeout(250);result.checks.push({kind:'tool-resize',saved:await page.evaluate(()=>window.settings.getState().workspaceToolWidth),width:(await geometry(page.locator('.xy-review-workbench'))).width});}
 }
 await page.evaluate(()=>window.ws.getState().setOpen(false));await page.setViewportSize({width:720,height:480});
 await page.locator('.xy-chat-surface.xy-hover-scroll').evaluate(e=>e.scrollTop=240);await page.waitForTimeout(200);const scrollBefore=await page.locator('.xy-chat-surface.xy-hover-scroll').evaluate(e=>e.scrollTop);
 await page.evaluate(()=>{window.ws.getState().setOpen(true);window.ws.getState().setActiveTool('browser');});await page.waitForTimeout(250);await page.locator('.xy-review-workbench').getByRole('button',{name:'收起工作区',exact:true}).click();await page.waitForTimeout(250);result.checks.push({kind:'chat-restored',before:scrollBefore,after:await page.locator('.xy-chat-surface.xy-hover-scroll').evaluate(e=>e.scrollTop),input:await geometry(page.locator('.xy-composer-card textarea'))});
 for(const smoothness of [false,true])for(const kind of ['plan','permission','ask','wizard','multiple']){
  await page.evaluate(({kind,smoothness})=>{
   window.settings.getState().update({smoothness});const s=window.__XEYO_CHAT__,sessionId=s.getState().activeId;
   s.setState({pendingPlan:['plan','multiple'].includes(kind)?{requestId:'plan-'+smoothness,sessionId,plan:'检查页面、保留并发修改、验证交互。\n'.repeat(60)}:null,pendingPermission:['permission','multiple'].includes(kind)?{requestId:'permission-'+smoothness,sessionId,toolName:'Bash',prompt:'echo "只用于布局检查"\n'.repeat(60),reason:'confirm'}:null,pendingAsk:['ask','wizard','multiple'].includes(kind)?{requestId:'ask-'+kind+smoothness,sessionId,question:'优先检查哪个部分？'.repeat(50),options:['常用功能','设置和扩展','所有页面'],questions:kind==='wizard'?[{id:'q1',question:'优先检查哪个部分？'.repeat(40),options:[{label:'常用功能'},{label:'设置和扩展'}],multiSelect:false},{id:'q2',question:'第二题',options:[],multiSelect:false}]:[]}:null});
  },{kind,smoothness});await page.waitForTimeout(350);
  const control=kind==='plan'?page.getByRole('button',{name:'允许执行',exact:true}):['permission','multiple'].includes(kind)?page.getByRole('button',{name:'允许',exact:true}):kind==='wizard'?page.getByRole('button',{name:'跳过',exact:true}):page.locator('.xy-panel-ask-send:visible');
  result.checks.push({kind:'task',task:kind,smoothness,control:await geometry(control),input:await geometry(page.locator('.xy-composer-card textarea')),tabs:await page.getByRole('tablist',{name:'当前任务'}).count()});await shot(`task-${kind}-${smoothness}`);
  if(kind==='multiple' && await page.getByRole('tablist',{name:'当前任务'}).count()){
   await page.getByRole('tab',{name:'提问',exact:true}).click();await page.getByPlaceholder('或自由输入…').fill('保留这份草稿');await page.getByRole('tab',{name:'计划',exact:true}).click();await page.getByRole('tab',{name:'提问',exact:true}).click();result.checks.push({kind:'task-draft',smoothness,value:await page.getByPlaceholder('或自由输入…').inputValue()});
  }
 }
 await page.evaluate(()=>{window.__XEYO_CHAT__.setState({pendingAsk:null,pendingPermission:null,pendingPlan:null});window.settings.getState().update({smoothness:false});});await page.waitForTimeout(250);
 await settings('accounts');await page.getByRole('button',{name:'编辑此账号'}).first().click();
 const protocol=page.getByRole('combobox',{name:'API 协议',exact:true});result.checks.push({kind:'protocol',explicit:await protocol.count()});
 const url=page.locator('input').filter({visible:true});
 const address=page.getByPlaceholder(/https:\/\//).first();
 await address.fill('https://api.anthropic.com');if(await protocol.count())await protocol.selectOption('anthropic');
 await page.getByRole('button',{name:'从厂商拉取模型列表',exact:true}).click();await page.getByRole('button',{name:/重新拉取/}).waitFor();
 await page.getByRole('button',{name:'保存修改',exact:true}).click();
 result.checks.push({kind:'account-save',profile:await page.evaluate(()=>{const p=window.settings.getState().profiles.find(p=>p.id==='audit');return {provider:p.provider,baseUrl:p.baseUrl};})});await shot('accounts');
 await closeSettings();await settings('rewind');
 result.checks.push({kind:'rewind',size:await page.getByLabel(/单个对话的存储上限/).inputValue(),help:await geometry(page.getByText(/默认只恢复本轮 Agent/)),technicalExposed:await page.getByText(/Shadow Git/).count()});await shot('rewind');
 await closeSettings();await settings('remote');result.checks.push({kind:'remote-management',connect:await page.getByRole('button',{name:'连接微信',exact:true}).count(),refresh:await page.getByRole('button',{name:'刷新状态',exact:true}).count()});await shot('remote');await closeSettings();
 await page.getByRole('button',{name:'应用菜单',exact:true}).click();result.checks.push({kind:'app-menu',text:await page.getByRole('menu').innerText()});await shot('app-menu');await page.keyboard.press('Escape');
 await page.getByRole('navigation',{name:'应用导航'}).getByRole('button',{name:'扩展',exact:true}).click();await page.getByTestId('extensions-panel').waitFor({timeout:45000});
 const add=page.getByRole('button',{name:'添加 / 导入配置'});result.checks.push({kind:'extensions',add:await add.count()});
 if(await add.count()){
  await add.click();await page.getByLabel('扩展配置 JSON').waitFor();await page.getByText('填写新的 MCP 服务器',{exact:true}).click();await page.getByLabel('MCP 名称',{exact:true}).fill('example');await page.getByLabel('MCP 启动程序',{exact:true}).fill('example-installed-server');await page.getByRole('button',{name:'加入配置草稿'}).click();
  result.checks.push({kind:'config-save-before-validation',disabled:await page.getByRole('button',{name:'保存配置',exact:true}).isDisabled()});await page.getByRole('button',{name:'校验配置',exact:true}).click();await page.getByText('格式校验通过。尚未保存，也未启动任何扩展。').waitFor();await page.getByRole('button',{name:'保存配置',exact:true}).click();await page.getByText(/^已保存。新的 MCP/).waitFor();await shot('extensions-config');
  const edited=JSON.stringify({servers:{example:{command:'changed-local-server'}}},null,2);await page.getByLabel('扩展配置 JSON').fill(edited);await page.getByRole('button',{name:'校验配置',exact:true}).click();await page.getByText('格式校验通过。尚未保存，也未启动任何扩展。').waitFor();configRev='c'.repeat(64);await page.getByRole('button',{name:'保存配置',exact:true}).click();await page.getByRole('alert').filter({hasText:'配置已被其他操作修改'}).waitFor();result.checks.push({kind:'config-conflict',draftKept:(await page.getByLabel('扩展配置 JSON').inputValue())===edited,saveDisabled:await page.getByRole('button',{name:'保存配置',exact:true}).isDisabled()});
 }
 await page.getByRole('navigation',{name:'应用导航'}).getByRole('button',{name:'诊断',exact:true}).click();await page.getByTestId('diagnostics-panel').waitFor({timeout:45000});result.checks.push({kind:'diagnostics',groups:await page.locator('[aria-label="诊断分组"]').count(),experimentPrimary:await page.getByRole('tab',{name:'实验',exact:true}).count()});await shot('diagnostics');
 if(await page.getByRole('button',{name:'高级实验',exact:true}).count()){await page.getByRole('button',{name:'高级实验',exact:true}).click();result.checks.push({kind:'advanced-access',tab:await page.getByRole('tab',{name:'实验',exact:true}).count()});}
 await page.goto(origin+'/bench/chat?rounds=4&bench=1',{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>!!window.__XY_REPLAY__);await page.evaluate(async()=>{window.auditImport=p=>import(performance.getEntriesByType('resource').find(e=>new URL(e.name).pathname===p)?.name??p);window.ws=(await window.auditImport('/src/stores/workspaceStore.ts')).useWorkspaceStore;});
 await page.evaluate(()=>{const s=window.__XEYO_CHAT__,id=s.getState().activeId;s.setState({messagesById:{...s.getState().messagesById,[id]:[{id:'u',role:'user',text:'检查',createdAt:1},{id:'t1',role:'tool',toolName:'Bash',toolUseId:'bash',toolInput:JSON.stringify({command:'echo hello'}),toolStatus:'success',text:'hello',createdAt:2},{id:'t2',role:'tool',toolName:'Search',toolUseId:'search',toolInput:JSON.stringify({query:'layout problem'}),toolStatus:'success',text:'found',createdAt:3}]}});window.ws.getState().setOpen(true);window.ws.getState().setActiveTool('history');});
 await page.getByRole('button',{name:'复制命令',exact:true}).first().waitFor();const filter=page.getByLabel('筛选调用工具');result.checks.push({kind:'call-filter',available:await filter.count()});if(await filter.count()){await filter.selectOption('Search');result.checks.push({kind:'filtered-call',shellCopyButtons:await page.getByRole('button',{name:'复制命令',exact:true}).count(),searchSummary:await page.getByRole('button',{name:'layout problem',exact:true}).count()});}await shot('call-history');
}catch(e){result.failure=String(e);await shot('failure');throw e;}finally{fs.writeFileSync(out+'/evidence.json',JSON.stringify(result,null,2));await browser.close();console.log(JSON.stringify(result,null,2));}

if(process.env.GUI_SCOPE_BASELINE!=='1'){
 assert.deepEqual(result.errors,[]);
 const checks=kind=>result.checks.filter(c=>c.kind===kind),one=kind=>checks(kind)[0];
 assert.equal(one('initial-workspace').open,false);
 for(const c of checks('tool')){assert.equal(c.input.reachable,true);if(c.width===720)assert.ok(c.pane.width>=600);}
 assert.equal(one('tool-resize').saved,one('tool-resize').width);
 assert.equal(one('chat-restored').before,one('chat-restored').after);
 assert.equal(checks('task').length,10);for(const c of checks('task')){assert.equal(c.control.reachable,true,JSON.stringify(c));assert.equal(c.input.reachable,true);}
 for(const c of checks('task-draft'))assert.equal(c.value,'保留这份草稿');
 assert.equal(one('protocol').explicit,1);assert.equal(one('account-save').profile.provider,'anthropic');
 assert.equal(result.requests.find(r=>r.path==='/v1/models').provider,'anthropic');
 assert.equal(one('rewind').size,'100');assert.equal(one('rewind').technicalExposed,0);
 assert.equal(one('remote-management').connect,1);assert.equal(one('remote-management').refresh,1);
 assert.equal(one('extensions').add,1);assert.equal(one('config-save-before-validation').disabled,true);assert.equal(one('config-conflict').draftKept,true);
 assert.equal(one('diagnostics').groups,1);assert.equal(one('diagnostics').experimentPrimary,0);assert.equal(one('advanced-access').tab,1);
 assert.equal(one('call-filter').available,1);assert.equal(one('filtered-call').shellCopyButtons,0);assert.equal(one('filtered-call').searchSummary,1);
}
