import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {REVIEW_LAYOUT_ENABLED} from '@/lib/reviewLayout';

/** 在所选预览的同一界面区域内复用设置字段。 */
export function SettingsLayoutHost({children}: {children: ReactNode}) {
	const host = REVIEW_LAYOUT_ENABLED ? document.querySelector('.xy-pane-chat-host') : null;
	return host ? createPortal(children, host) : children;
}
