import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import {isTauri} from '@/lib/tauri';
import {parseJsonValue} from '@/lib/safeJson';
import {applyDocumentTheme, type ThemeId} from '@/stores/settingsStore';
import {normalizeThemeId} from '@/theme/catalog';
import {bindWorkspaceExplorerSync} from '@/stores/workspaceExplorerSync';
import {preloadMermaid} from '@/lib/mermaidRender';
import './styles/entry.css';
import '@/pet/pet.css';

if (isTauri()) {
	document.documentElement.classList.add('tauri');
}

document.addEventListener(
	'contextmenu',
	e => {
		e.preventDefault();
	},
	true,
);

// 首次绘制前应用主题，避免闪烁
try {
	const raw = localStorage.getItem('xeyo-settings') || localStorage.getItem('xy-agent-settings');
	const theme = normalizeThemeId(
		parseJsonValue<{theme?: ThemeId}>(raw)?.theme,
	);
	applyDocumentTheme(theme);
} catch {
	applyDocumentTheme('paper');
}

bindWorkspaceExplorerSync();

// 预热 mermaid 动态 chunk（首条图渲染前先加载，降低 wasm/worker 受限环境的冷启动失败）。
preloadMermaid();

// DEV / e2e：暴露 chat store 供 Playwright 注入「打开的文件夹」工作区。
// 仅 dev 构建生效（生产 import.meta.env.DEV 为 false），不改变任何生产行为。
if (import.meta.env.DEV) {
	import('@/stores/chatStore').then(({useChatStore}) => {
		(window as unknown as Record<string, unknown>).__XEYO_CHAT__ = useChatStore;
	});
}

createRoot(document.getElementById('root')!).render(
	<StrictMode>
		<App />
	</StrictMode>,
);

if (isTauri()) {
	requestAnimationFrame(() =>
		requestAnimationFrame(() => {
			void import('@tauri-apps/api/window')
				.then(({getCurrentWindow}) => getCurrentWindow().show())
				.catch(() => {});
		}),
	);
}
