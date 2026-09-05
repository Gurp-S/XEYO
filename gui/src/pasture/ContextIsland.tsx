import {lazy, Suspense} from 'react';

/**
 * 语境岛入口。本模块不引入 chat store / 场景依赖，
 * 使关闭岛屿时启动阶段不会拉取 pasture CSS 或订阅 usage。
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
