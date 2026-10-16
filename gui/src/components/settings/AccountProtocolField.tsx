import type {ProviderId} from '@/stores/settingsStore';
export const ACCOUNT_PROTOCOLS = [
 {id:'openai',label:'OpenAI 兼容'}, {id:'anthropic',label:'Anthropic Messages'}, {id:'deepseek',label:'DeepSeek'},
] as const;
export function AccountProtocolField({value,onChange}: {value:ProviderId;onChange:(value:ProviderId)=>void}) {
 return <label className="xy-settings-field"><span>API 协议</span>
  <select aria-label="API 协议" value={value} onChange={e=>onChange(e.target.value as ProviderId)}>
   {ACCOUNT_PROTOCOLS.map(p=><option key={p.id} value={p.id}>{p.label}</option>)}
   {value==='local' && <option value="local">开发测试协议</option>}
  </select><small>按服务商或中转服务的接口协议选择；修改地址不会改变协议。</small>
 </label>;
}
