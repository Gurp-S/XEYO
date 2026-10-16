import {lazy, Suspense, useRef} from 'react';

const Settings = lazy(() => import('./SettingsModal').then(module => ({default: module.SettingsModal})));

/** Load on first opening, then retain the component to preserve drafts/exit motion. */
export function DeferredSettingsModal(props: {open: boolean; onClose: () => void}) {
	const requested = useRef(false);
	if (props.open) requested.current = true;
	return requested.current ? <Suspense fallback={null}><Settings {...props} /></Suspense> : null;
}
