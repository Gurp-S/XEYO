import type {ReactNode} from 'react';
import {useWorkspaceStore} from '@/stores/workspaceStore';
export function VersionControlView({view,children}:{view:'git'|'commits';children:ReactNode}) {
 return <div className="xy-version-view"><nav aria-label="版本控制视图">{(['git','commits'] as const).map(key=><button key={key} aria-current={view===key?'page':undefined} onClick={()=>useWorkspaceStore.getState().setActiveTool(key)}>{key==='git'?'工作区状态':'提交记录'}</button>)}</nav><div>{children}</div></div>;
}
