import {useEffect} from 'react';
import {useRemoteStore} from '@/stores/remoteStore';
export function RemoteSettingsHelp() {
 const {state,loggedIn,busy,pollError,error,hint,hasQr,startRemote,stopRemote,pollRemote,setPanelOpen} = useRemoteStore();
 useEffect(()=>{void pollRemote();},[pollRemote]);
 const status = pollError ? '状态读取失败' : busy ? '处理中' : loggedIn ? '已连接' : hasQr ? '等待扫码' : state==='error' ? '连接失败' : '未连接';
 return <section className="space-y-4 text-sm leading-relaxed">
  <h3 className="xy-section-label">微信远程</h3>
  <p>用手机继续桌面的对话，支持文字、图片和文件。</p>
  <div className="xy-remote-management"><strong role="status">{status}</strong>
   {(pollError || error) && <p role="alert">{pollError || error}</p>}{hint && <p>{hint}</p>}
   <div className="flex flex-wrap gap-2">
    {loggedIn ? <button disabled={busy} onClick={()=>void stopRemote()}>断开连接</button> : <button disabled={busy} onClick={()=>hasQr ? setPanelOpen(true) : void startRemote()}>{hasQr ? '显示二维码' : '连接微信'}</button>}
    <button disabled={busy} onClick={()=>void pollRemote()}>刷新状态</button>
   </div>
  </div>
  <p>连接时会显示二维码。用微信扫码并确认后，即可在手机上发送消息。</p>
  <details><summary>常用指令</summary><dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-5 gap-y-2"><dt>/help</dt><dd>查看帮助</dd><dt>/status</dt><dd>连接与任务状态</dd><dt>/cwd</dt><dd>当前工作区</dd><dt>/stop</dt><dd>停止当前任务</dd><dt>/allow · /deny</dt><dd>批准或拒绝待确认操作</dd></dl></details>
 </section>;
}
