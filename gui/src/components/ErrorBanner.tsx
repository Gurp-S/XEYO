import {AlertCircle, X} from 'lucide-react';
import {useMemo, useRef, useState} from 'react';
import {healthCheck} from '@/lib/api';
import {refreshRuntimeBackendPort} from '@/lib/apiBase';
import {errorBannerMatchesActiveSession} from '@/lib/pendingForSession';
import {useChatUiStore} from '@/stores/chatUiStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {DockPresence} from './DockPresence';

export type ErrorCategory = 'settings' | 'quota' | 'network' | null;

/** 错误文案分类：决定右侧直达动作（settings 优先，其次 quota / network）。 */
export function classifyError(msg: string): ErrorCategory {
	if (/api key|401|authentication|设置|鉴权/i.test(msg)) {
		return 'settings';
	}
	if (/429|quota|额度|配额|rate.?limit/i.test(msg)) {
		return 'quota';
	}
	if (/timeout|超时|econnrefused|无法连接|network|fetch failed|请求超时/i.test(msg)) {
		return 'network';
	}
	return null;
}

type Props = {
	/** 嵌入 Composer 时不包外层 padding。 */
	embedded?: boolean;
};

/**
 * 输入框上方可关闭的错误条（Task5）。
 * 保持聊天历史完整 — 错误显示在此，而非系统气泡。
 */
export function ErrorBanner({embedded = false}: Props) {
	const activeId = useChatUiStore(s => s.activeId);
	const errorBanner = useChatUiStore(s => s.errorBanner);
	const errorBannerSessionId = useChatUiStore(s => s.errorBannerSessionId);
	const clearErrorBanner = useChatUiStore(s => s.clearErrorBanner);
	const openSettings = useSettingsStore(s => s.openSettings);
	const openUsage = useSettingsStore(s => s.openUsage);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const [retrying, setRetrying] = useState(false);
	const holdRef = useRef('');
	const visibleBanner = useMemo(
		() =>
			errorBanner &&
			errorBannerMatchesActiveSession(errorBannerSessionId, activeId)
				? errorBanner
				: null,
		[errorBanner, errorBannerSessionId, activeId],
	);
	if (visibleBanner) {
		holdRef.current = visibleBanner;
	}

	const live = Boolean(visibleBanner);
	const text = visibleBanner ?? holdRef.current;
	const category = classifyError(text);

	const retryConnection = async () => {
		if (retrying) {
			return;
		}
		setRetrying(true);
		try {
			// 静默探测后端；不再弹出右下角 toast（smoke-test：删除该弹窗）。
			// 先刷新运行时端口（守护 respawn / 端口迁移后前端才能跟到新端口）。
			await refreshRuntimeBackendPort();
			const ok = await healthCheck();
			if (ok) {
				// 后端恢复：触发 active 会话重连（reattach），而非只清 banner。
				clearErrorBanner();
				const {useChatStore} = await import('@/stores/chatStore');
				void useChatStore.getState().reattachActiveStreams();
			}
		} finally {
			setRetrying(false);
		}
	};

	const bar = text ? (
		<div className="xy-error-banner flex w-full items-start gap-2 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] leading-snug text-ink">
			<AlertCircle
				className="mt-0.5 size-3.5 shrink-0 text-danger"
				aria-hidden
			/>
			<p className="min-w-0 flex-1 font-sans text-ink-soft">{text}</p>
			{category ? (
				<button
					type="button"
					disabled={category === 'network' && retrying}
					className="shrink-0 self-start pt-px font-sans text-[11px] text-accent underline decoration-current underline-offset-2 transition-colors duration-150 hover:text-accent-hover disabled:opacity-50"
					onClick={() => {
						if (category === 'settings') {
							openSettings();
						} else if (category === 'quota') {
							openUsage();
						} else {
							void retryConnection();
						}
					}}
				>
					{category === 'settings'
						? '打开设置'
						: category === 'quota'
							? '打开用量面板'
							: retrying
								? '重试中…'
								: '重试连接'}
				</button>
			) : null}
			<button
				type="button"
				aria-label="关闭错误提示"
				className="shrink-0 rounded-md p-0.5 text-mute hover:bg-glass-hover hover:text-ink"
				onClick={() => clearErrorBanner()}
			>
				<X className="size-3.5" />
			</button>
		</div>
	) : null;

	return (
		<DockPresence open={live} smoothness={smoothness}>
			{bar
				? embedded
					? bar
					: (
						<div className="shrink-0 px-3 pb-1 sm:px-5">
							<div className="mx-auto w-full max-w-3xl">{bar}</div>
						</div>
					)
				: null}
		</DockPresence>
	);
}
