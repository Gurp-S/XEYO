import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {REVIEW_LAYOUT_ENABLED} from '@/lib/reviewLayout';

/** Reuse the settings fields inside the same surface as the selected preview. */
export function SettingsLayoutHost({children}: {children: ReactNode}) {
	const host = REVIEW_LAYOUT_ENABLED ? document.querySelector('.xy-pane-chat-host') : null;
	return host ? createPortal(children, host) : children;
}
