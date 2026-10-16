import {apiUrl} from '@/lib/apiBase';
import {authHeaders,fetchWithTimeout,formatErrorDetail} from './core';
export type ConfigurationScope='workspace'|'home';
export type ConfigurationKind='mcp'|'settings';
export type ConfigurationDocument={ok:true;scope:ConfigurationScope;kind:ConfigurationKind;path:string;revision:string;data:Record<string,unknown>};
export async function readExtensionConfiguration(scope:ConfigurationScope,kind:ConfigurationKind,workspace:string,signal?:AbortSignal):Promise<ConfigurationDocument> {
 const query=new URLSearchParams({scope,kind,...(workspace?{workspace}:{})});
 const response=await fetchWithTimeout(apiUrl(`/v1/extensions/configuration?${query}`),{headers:authHeaders(),signal,cache:'no-store'});
 const data=await response.json();
 if(!response.ok || data.ok!==true) throw new Error(formatErrorDetail(data,response.status));
 return data;
}
export async function saveExtensionConfiguration(document:ConfigurationDocument,workspace:string,data:Record<string,unknown>,validateOnly:boolean):Promise<{revision:string;saved:boolean}> {
 const response=await fetchWithTimeout(apiUrl('/v1/extensions/configuration'),{method:'POST',headers:{...authHeaders(),'Content-Type':'application/json'},body:JSON.stringify({scope:document.scope,kind:document.kind,workspace:workspace||undefined,revision:document.revision,data,validate_only:validateOnly})});
 const result=await response.json();
 if(response.status===409) throw new Error('配置已被其他操作修改。草稿仍保留；重新读取后再合并你的改动。');
 if(!response.ok || result.ok!==true) throw new Error(formatErrorDetail(result,response.status));
 return result;
}
