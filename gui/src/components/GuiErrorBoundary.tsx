import {Component, type ErrorInfo, type ReactNode} from 'react';
import {isTauri} from '@/lib/tauri';

type Props = {children: ReactNode};
type State = {error: Error | null};

function revealTauriWindow() {
	if (!isTauri()) {
		return;
	}
	void import('@tauri-apps/api/window')
		.then(({getCurrentWindow}) => getCurrentWindow().show())
		.catch(() => {});
}

let hmrAutoReloadHooked = false;

/**
 * 崩溃后常规 HMR 无法恢复（boundary 的 error state 会被 react-refresh 保留），
 * 只能手动刷新。自改 GUI 的场景下，改为监听下一次 HMR 更新时整页重载自愈。
 */
function hookHmrAutoReload() {
	if (hmrAutoReloadHooked || !import.meta.hot) {
		return;
	}
	hmrAutoReloadHooked = true;
	import.meta.hot.on('vite:afterUpdate', () => window.location.reload());
}

/** Prevent a render throw from leaving the transparent Tauri shell fully black. */
export class GuiErrorBoundary extends Component<Props, State> {
	state: State = {error: null};

	static getDerivedStateFromError(error: Error): State {
		return {error};
	}

	componentDidCatch(error: Error, info: ErrorInfo) {
		console.error('[XEYO GUI]', error, info.componentStack);
		revealTauriWindow();
		hookHmrAutoReload();
	}

	render() {
		if (this.state.error) {
			return (
				<div className="flex h-full min-h-[200px] flex-col items-start justify-center gap-3 bg-paper p-8 text-ink">
					<p className="font-sans text-lg font-medium">界面渲染出错</p>
					<p className="text-sm text-mute">
						点击「重新加载」即可恢复。若反复出现，请展开技术详情并反馈。
					</p>
					{/* T34：不再默认裸出异常文本；折叠为可选技术详情。 */}
					<details className="max-h-[40vh] w-full overflow-auto rounded-lg border border-line bg-glass p-3">
						<summary className="cursor-pointer text-xs text-mute">技术详情</summary>
						<pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-danger">
							{this.state.error.message}
						</pre>
					</details>
					<button
						type="button"
						className="rounded-lg bg-glass-strong px-4 py-2 text-sm"
						onClick={() => window.location.reload()}
					>
						重新加载
					</button>
				</div>
			);
		}
		return this.props.children;
	}
}
