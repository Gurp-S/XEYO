import {useEffect,useRef,useState} from 'react';
import {readExtensionConfiguration,saveExtensionConfiguration,type ConfigurationDocument,type ConfigurationKind,type ConfigurationScope} from '@/lib/api/extensionConfiguration';
import {confirmDialog} from '@/lib/inlineDialog';
import {useChatStore} from '@/stores/chatStore';

export function ExtensionConfiguration({onSaved}:{onSaved:()=>void}) {
 const workspace=useChatStore(s=>s.spaces.find(space=>space.id===s.activeSpaceId)?.rootPath || '');
 const [open,setOpen]=useState(false);
 const [opened,setOpened]=useState(false);
 // A workspace switch remounts the editor so an old document can never target the new root.
 return <section className="xy-extension-config"><header><div><h3>扩展管理</h3><p>管理本机与工作区声明。已有插件和技能可在下方启停。</p></div><button aria-expanded={open} onClick={()=>{setOpened(true);setOpen(v=>!v);}}>添加 / 导入配置</button></header>
 {opened && <div hidden={!open}><ConfigurationEditor key={workspace} workspace={workspace} onSaved={onSaved}/></div>}
 </section>;
}

function ConfigurationEditor({workspace,onSaved}:{workspace:string;onSaved:()=>void}) {
 const [scope,setScope]=useState<ConfigurationScope>(workspace?'workspace':'home');
 const [kind,setKind]=useState<ConfigurationKind>('mcp');
 const [document,setDocument]=useState<ConfigurationDocument|null>(null);
 const [draft,setDraft]=useState('');const [initial,setInitial]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [validated,setValidated]=useState(false),[reload,setReload]=useState(0);
 const [server,setServer]=useState(''),[command,setCommand]=useState(''),[args,setArgs]=useState('');
 const file=useRef<HTMLInputElement>(null),inFlight=useRef(false),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 useEffect(()=>{
  const controller=new AbortController();setBusy(true);setDocument(null);setError('');setNotice('');setValidated(false);
  void readExtensionConfiguration(scope,kind,workspace,controller.signal).then(doc=>{
   if(controller.signal.aborted)return;setDocument(doc);const text=JSON.stringify(doc.data,null,2);setDraft(text);setInitial(text);
  }).catch(e=>{if(!controller.signal.aborted)setError(String(e.message||e));}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  return()=>controller.abort();
 },[scope,kind,workspace,reload]);
 const changeDraft=(text:string)=>{setDraft(text);setValidated(false);setNotice('');};
 const canDiscard=async()=>draft===initial || await confirmDialog({title:'离开配置草稿？',body:'当前未保存的配置草稿将被丢弃。',confirmText:'丢弃草稿'});
 const submit=async(validateOnly:boolean)=>{
  if(!document || inFlight.current)return;
  inFlight.current=true;setBusy(true);setError('');setNotice('');
  try {
   const data=JSON.parse(draft);if(!data || typeof data!=='object' || Array.isArray(data))throw new Error('配置需要是 JSON 对象');
   const result=await saveExtensionConfiguration(document,workspace,data,validateOnly);
   if(!alive.current)return;
   setValidated(true);
   if(result.saved){setDocument({...document,revision:result.revision,data});setInitial(draft);setNotice('已保存。新的 MCP 声明在下次创建或重新加载会话时读取；工作区声明仍需在列表中批准。');onSaved();}
   else setNotice('格式校验通过。尚未保存，也未启动任何扩展。');
  } catch(e){if(alive.current){setValidated(false);setError(e instanceof Error?e.message:String(e));}}
  finally {inFlight.current=false;if(alive.current)setBusy(false);}
 };
 const addServer=()=>{
  try {
   if(!server.trim() || !command.trim())throw new Error('请填写名称和启动程序');
   const data=JSON.parse(draft);if(data.servers?.[server.trim()])throw new Error('已有同名服务器，请在配置中编辑它');
   changeDraft(JSON.stringify({...data,servers:{...data.servers,[server.trim()]:{command:command.trim(),args:args.split('\n').filter(Boolean)}}},null,2));setError('');
  }catch(e){setError(e instanceof Error?e.message:String(e));}
 };
 return <div className="xy-configuration-editor">
  <div className="xy-configuration-selectors"><label>作用范围<select aria-label="配置作用范围" value={scope} disabled={busy} onChange={async e=>{const value=e.target.value as ConfigurationScope;if(await canDiscard())setScope(value);}}>{workspace&&<option value="workspace">当前工作区</option>}<option value="home">本机所有工作区</option></select></label>
  <label>配置内容<select aria-label="配置内容" value={kind} disabled={busy} onChange={async e=>{const value=e.target.value as ConfigurationKind;if(await canDiscard())setKind(value);}}><option value="mcp">MCP 服务器声明</option><option value="settings">扩展、插件与技能开关</option></select></label></div>
  {document&&<><p className="xy-configuration-source">保存位置：{document.path}</p>
   <p>{kind==='mcp'?'目前支持通过启动程序连接的 MCP（stdio）。保存声明后，在 MCP 列表中启用；工作区配置需要批准。':'配置已有插件、技能和 MCP 的开关，不会下载或安装扩展。工作区同名设置覆盖本机设置。'}</p>
   {kind==='mcp'&&<details><summary>填写新的 MCP 服务器</summary><div className="xy-configuration-selectors"><label>名称<input aria-label="MCP 名称" value={server} disabled={busy} onChange={e=>setServer(e.target.value)}/></label><label>启动程序<input aria-label="MCP 启动程序" value={command} disabled={busy} onChange={e=>setCommand(e.target.value)} placeholder="例如：已安装的程序完整路径"/></label></div><label>启动参数（每行一个）<textarea aria-label="MCP 启动参数" rows={2} disabled={busy} value={args} onChange={e=>setArgs(e.target.value)}/></label><button disabled={busy} onClick={addServer}>加入配置草稿</button></details>}
   {kind==='settings'&&<button disabled={busy} onClick={()=>{try{changeDraft(JSON.stringify({...JSON.parse(draft),enabled_extensions:true},null,2));}catch{setError('先修正 JSON 格式再添加总开关');}}}>在草稿中开启扩展</button>}
   <label>配置 JSON<textarea aria-label="扩展配置 JSON" spellCheck={false} rows={8} disabled={busy} value={draft} onChange={e=>changeDraft(e.target.value)}/></label>
   <input hidden ref={file} type="file" accept=".json,application/json" onChange={async e=>{const selected=e.target.files?.[0];if(!selected)return;try{if(selected.size>256*1024)throw new Error('配置文件不能超过 256 KiB');const text=await selected.text();JSON.parse(text);if(await canDiscard())changeDraft(text);}catch(e){setError(e instanceof Error?e.message:String(e));}finally{if(file.current)file.current.value='';}}}/>
   <footer><button disabled={busy} onClick={()=>file.current?.click()}>导入 JSON</button><button disabled={busy} onClick={()=>void submit(true)}>校验配置</button><button disabled={busy||!validated||draft===initial} onClick={()=>void submit(false)}>保存配置</button><button disabled={busy} onClick={async()=>{if(await canDiscard())setReload(v=>v+1);}}>重新读取</button></footer>
  </>}
  {!document&&!busy&&<button onClick={()=>setReload(v=>v+1)}>重试读取配置</button>}
  {busy&&<p role="status">处理中…</p>}{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
 </div>;
}
