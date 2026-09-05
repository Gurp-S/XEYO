import {lazy, Suspense} from 'react';

/**
 * Context island entry. Keep this module free of chat store / scene imports so a
 * disabled island does not pull pasture CSS or subscribe to usage on boot.
 */
export const CONTEXT_ISLAND_RENDER_ENABLED = false;

const ContextIslandRuntime = lazy(() =>
	import('./ContextIslandRuntime').then(m => ({
		default: m.ContextIslandRuntime,
	})),
);

export function ContextIsland() {
	if (!CONTEXT_ISLAND_RENDER_ENABLED) {
		return null;
	}
	return (
		<Suspense fallback={null}>
			<ContextIslandRuntime />
		</Suspense>
	);
}
