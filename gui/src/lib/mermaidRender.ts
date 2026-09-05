type MermaidApi = {
	initialize: (opts: Record<string, unknown>) => void;
	render: (
		id: string,
		src: string,
	) => Promise<{svg: string}>;
};

const CACHE_CAP = 30;
const cache = new Map<string, string>();
let mermaidPromise: Promise<MermaidApi> | null = null;
let themeApplied = '';
let seq = 0;

function mermaidInit(theme?: 'dark' | 'default'): Record<string, unknown> {
	return {
		startOnLoad: false,
		securityLevel: 'strict',
		fontFamily: 'inherit',
		// 解析失败时不要把「Syntax error」图插进 body，否则整窗会被撑出滚动条。
		suppressErrorRendering: true,
		...(theme ? {theme} : {}),
	};
}

function sweepMermaidTemps(id: string) {
	document.getElementById(id)?.remove();
	document.getElementById(`d${id}`)?.remove();
}

function loadMermaid(): Promise<MermaidApi> {
	if (!mermaidPromise) {
		mermaidPromise = import('mermaid').then(mod => {
			const api = (mod.default ?? mod) as MermaidApi;
			api.initialize(mermaidInit());
			return api;
		});
	}
	return mermaidPromise;
}

/** 预热 mermaid 动态 chunk：在 app 启动早期调用，降低首条图渲染时
「动态 import + 初始化」的冷启动失败概率（Tauri WebView 的 wasm/worker 受限场景）。 */
export function preloadMermaid(): void {
	void loadMermaid().catch(() => {
		/* 预热失败静默；首条图渲染时会有具体诊断 */
	});
}

export function mermaidCacheKey(source: string, theme: string): string {
	return `${theme}\0${source}`;
}

export function getCachedMermaidSvg(
	source: string,
	theme: string,
): string | undefined {
	return cache.get(mermaidCacheKey(source, theme));
}

export async function renderMermaidSvg(
	source: string,
	theme: 'dark' | 'default',
): Promise<string> {
	const key = mermaidCacheKey(source, theme);
	const hit = cache.get(key);
	if (hit) {
		return hit;
	}
	const api = await loadMermaid();
	if (themeApplied !== theme) {
		api.initialize(mermaidInit(theme));
		themeApplied = theme;
	}
	seq += 1;
	const id = `xy-mmd-${seq}`;
	try {
		const {svg} = await api.render(id, source);
		cache.set(key, svg);
		while (cache.size > CACHE_CAP) {
			const oldest = cache.keys().next().value;
			if (oldest === undefined) {
				break;
			}
			cache.delete(oldest);
		}
		return svg;
	} catch (err) {
		sweepMermaidTemps(id);
		throw err;
	}
}

export function svgToImageUrl(svg: string): string {
	return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
