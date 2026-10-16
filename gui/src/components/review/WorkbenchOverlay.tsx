import {createContext, useContext, type ReactNode} from 'react';
import {createPortal} from 'react-dom';

export const WorkbenchOverlayHost = createContext<HTMLElement | null>(null);

/** 工作台嵌套后，放大的工具面板仍覆盖聊天容器。 */
export function WorkbenchOverlay({children}: {children: ReactNode}) {
 const host = useContext(WorkbenchOverlayHost);
 return host ? createPortal(children, host) : children;
}
