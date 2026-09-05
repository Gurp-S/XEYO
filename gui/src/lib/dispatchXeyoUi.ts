import {toast} from '@/lib/toast';
import {
	controlBrowserPreview,
	openWorkspacePanel,
	openWorkspacePreview,
	setMapToolFlowVisible,
	type BrowserUiOp,
} from '@/lib/openWorkspacePreview';

export type XeyoUiPayload = {
	action?: string;
	path?: string;
	panel?: string;
	url?: string;
	op?: string;
	show?: boolean;
	session_id?: string;
	text?: string;
};

/** reattach / late result 去重：同一 toolUseId 只分发一次副作用。 */
const dispatchedToolUseIds = new Set<string>();

const PANELS = new Set(['git', 'terminal', 'history', 'map', 'commits', 'browser']);
const BROWSER_OPS = new Set(['reload', 'back', 'fwd', 'ext', 'close']);

export function resetXeyoUiDispatchForTests(): void {
	dispatchedToolUseIds.clear();
}

/**
 * 处理 XeyoUI tool_result 旁路的 xy.ui。
 * send_to_session 不 await，避免堵住当前会话 SSE 处理。
 */
export function dispatchXeyoUi(
	ui: unknown,
	opts?: {toolUseId?: string; isError?: boolean},
): void {
	if (opts?.isError) {
		return;
	}
	if (!ui || typeof ui !== 'object') {
		return;
	}
	const payload = ui as XeyoUiPayload;
	const action = String(payload.action || '').trim();
	if (!action) {
		return;
	}
	const toolUseId = opts?.toolUseId?.trim();
	if (toolUseId) {
		if (dispatchedToolUseIds.has(toolUseId)) {
			return;
		}
		dispatchedToolUseIds.add(toolUseId);
		if (dispatchedToolUseIds.size > 200) {
			const first = dispatchedToolUseIds.values().next().value;
			if (first) {
				dispatchedToolUseIds.delete(first);
			}
		}
	}

	if (action === 'open_preview') {
		const path = String(payload.path || '').trim();
		if (!path) {
			return;
		}
		void openWorkspacePreview(path).catch(err => {
			toast.error(
				err instanceof Error ? err.message : `打开预览失败：${String(err)}`,
			);
		});
		return;
	}

	if (action === 'open_panel') {
		const panel = String(payload.panel || '').trim();
		if (!PANELS.has(panel)) {
			toast.error(`未知工作区面板：${panel || '(empty)'}`);
			return;
		}
		openWorkspacePanel(
			panel as 'git' | 'terminal' | 'history' | 'map' | 'commits' | 'browser',
		);
		return;
	}

	if (action === 'browser') {
		const url = String(payload.url || '').trim();
		const opRaw = String(payload.op || '').trim();
		if (url) {
			controlBrowserPreview({url});
			return;
		}
		if (opRaw) {
			if (!BROWSER_OPS.has(opRaw)) {
				toast.error(`未知浏览器操作：${opRaw}`);
				return;
			}
			controlBrowserPreview({op: opRaw as BrowserUiOp});
			return;
		}
		controlBrowserPreview({});
		return;
	}

	if (action === 'show_tool_flow') {
		setMapToolFlowVisible(payload.show === true);
		return;
	}

	if (action === 'send_to_session') {
		const sessionId = String(payload.session_id || '').trim();
		const text = String(payload.text || '').trim();
		if (!sessionId || !text) {
			return;
		}
		// 动态 import，避免与 streamSendSlice 循环依赖。
		void import('@/stores/chatStore')
			.then(({useChatStore}) => {
				const send = useChatStore.getState().sendToSession;
				if (!send) {
					toast.error('sendToSession 不可用');
					return;
				}
				return send(sessionId, text).then(ok => {
					if (ok) {
						const title =
							useChatStore
								.getState()
								.sessions.find(s => s.id === sessionId)?.title ||
							sessionId;
						toast.success(`已在后台向「${title}」发送`);
					}
				});
			})
			.catch(err => {
				toast.error(
					err instanceof Error
						? err.message
						: `跨对话发送失败：${String(err)}`,
				);
			});
	}
}
