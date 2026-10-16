import {lazy, Suspense} from 'react';
import type {XyStreamdownProps} from './XyStreamdown';

const Markdown = lazy(() => import('./XyStreamdown').then(module => ({default: module.XyStreamdown})));

/** The editor and empty chat do not need a Markdown parser at startup. */
export function DeferredMarkdown(props: XyStreamdownProps) {
	// The editor owns its boundary so its editable host mounts only after the
	// document is ready; a loading placeholder must never become saved content.
	if (props.editable) return <Markdown {...props} />;
	return <Suspense fallback={<div className="min-h-6 text-mute text-sm" role="status" aria-busy="true">正在加载正文…</div>}>
		<Markdown {...props} />
	</Suspense>;
}
