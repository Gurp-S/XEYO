import {createContext, useContext, type ReactNode} from 'react';
import {createPortal} from 'react-dom';

export const WorkbenchOverlayHost = createContext<HTMLElement | null>(null);

/** Enlarged tools keep covering the chat host after nesting the workbench. */
export function WorkbenchOverlay({children}: {children: ReactNode}) {
 const host = useContext(WorkbenchOverlayHost);
 return host ? createPortal(children, host) : children;
}
