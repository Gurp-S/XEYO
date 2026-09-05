import {useCallback, useEffect, useRef, useState} from 'react';
import {ChevronDown, X} from 'lucide-react';
import {resolvePermission} from '@/lib/api';
import {toast} from '@/lib/toast';
import {useHeartbeat} from '@/lib/heartbeat';
import {usePendingPermissionForActiveSession} from '@/hooks/usePendingForActiveSession';
import {useChatStore, type PendingPermissionInfo} from '@/stores/chatStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {cn} from '@/lib/utils';
import {DockPresence} from './DockPresence';
import {PanelCollapse} from './PanelCollapse';

/** 命令区域可显示的行数上限（超出即出现底部渐化 + 图标展开）。 */
const COLLAPSE_LINES = 3;
const LINE_HEIGHT = 18;

const PEER_CHOICES = new Set(['deny', 'remind', 'allow']);
/** T3：到期前 30s 高亮（与 PENDING_REMINDER_BEFORE_S 对齐）。 */
const EXPIRE_WARN_S = 30;

const INTENT_TITLE: Record<string, string> = {
	confirm: '请求批准',
	choice: '多会话冲突',
	'plan-review': '计划确认',
};

export function PermissionDialog() {
	const pending = usePendingPermissionForActiveSession();
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));

	return (
		<DockPresence open={Boolean(pending)} smoothness={smoothness}>
			{pending ? (
				<PermissionCard key={pending.requestId} pending={pending} />
			) : null}
		</DockPresence>
	);
}

function PermissionCard({pending}: {pending: PendingPermissionInfo}) {
	const prompt = pending.prompt ?? '';
	const cmdRef = useRef<HTMLDivElement | null>(null);
	const [isLong, setIsLong] = useState(false);
	// T3：面板默认展开——安全决策不应藏在折叠条里。
	const [expanded, setExpanded] = useState(true);
	const [expiring, setExpiring] = useState(false);
	// T10：「不再询问此类命令」——仅 Bash 确认型请求提供（前缀 always-allow）。
	const isBashConfirm =
		pending.toolName === 'Bash' && (pending.intent ?? 'confirm') === 'confirm';
	const [remember, setRemember] = useState(false);

	useEffect(() => {
		const el = cmdRef.current;
		if (!el) {
			return;
		}
		const check = () => setIsLong(el.scrollHeight > el.clientHeight + 1);
		check();
		const ro = new ResizeObserver(check);
		ro.observe(el);
		return () => ro.disconnect();
	}, [prompt, expanded]);

	// T3：倒计时——距到期 <30s 高亮（客户端计算，无需服务端推送）。
	// 全局 1s 心跳:共享单一定时器,替代自建 setInterval(见 lib/heartbeat.ts)
	const expiresAt = pending.expiresAt;
	const tickExpiring = useCallback(() => {
		if (!expiresAt) {
			setExpiring(false);
			return;
		}
		setExpiring(expiresAt - Date.now() / 1000 <= EXPIRE_WARN_S);
	}, [expiresAt]);
	useEffect(() => {
		tickExpiring();
	}, [tickExpiring]);
	useHeartbeat(tickExpiring, Boolean(expiresAt));

	const isPeerThree =
		Array.isArray(pending.choices) &&
		pending.choices.length >= 3 &&
		pending.choices.every(c => PEER_CHOICES.has(c));

	const decide = async (
		approved: boolean,
		outcome?: 'allow' | 'deny' | 'remind',
		withRemember = false,
	) => {
		// T3：先发送再清状态；HTTP 失败 → 回滚面板 + toast，不假装已处理。
		const ok = await resolvePermission(
			pending.requestId,
			approved,
			'desktop',
			outcome,
			withRemember,
		);
		if (!ok) {
			toast.error('提交审批结果失败，请重试');
			return;
		}
		if (withRemember) {
			toast.info('已记住：此类命令后续不再询问（可在设置中撤销）');
		}
		useChatStore.getState().setPendingPermission?.(null);
	};

	// T3：关闭 / Esc = 取消（deny），并toast提示。
	const cancel = () => {
		void decide(false, 'deny');
		toast.info('已取消该操作');
	};

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				e.preventDefault();
				cancel();
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [pending.requestId]);

	const intent = pending.intent ?? (isPeerThree ? 'choice' : 'confirm');
	const title = INTENT_TITLE[intent] ?? '请求批准';
	const toolLabel = pending.toolName || '工具';
	const clipped = isLong && expanded;
	const timeoutNote = pending.expiresAt
		? ` · ${expiring ? '即将超时并默认拒绝' : '超时后默认拒绝'}`
		: ' · 不超时，等待你的决定';

	return (
		<div
			className={cn(
				'xy-panel-ask',
				expanded && 'is-expanded',
				expiring && 'is-expiring',
			)}
			role="alertdialog"
			aria-label={title}
		>
			<div
				className="xy-panel-ask-head"
				aria-expanded={expanded}
				onClick={() => setExpanded(v => !v)}
			>
				<span className="xy-panel-ask-caret" aria-hidden="true">
					<ChevronDown
						className={cn(
							'size-3.5 transition-transform duration-200 ease-out',
							!expanded && '-rotate-90',
						)}
					/>
				</span>
				<span className="xy-panel-ask-title">{title}</span>
				<span className="xy-panel-ask-count">
					{toolLabel}
					{timeoutNote}
				</span>
				<span
					className={cn(
						'xy-panel-ask-dot',
						expiring ? 'is-danger animate-pulse' : 'is-danger',
					)}
					aria-hidden="true"
				/>
				<button
					type="button"
					className="ml-1 rounded p-0.5 text-mute/70 hover:bg-line/40 hover:text-fg"
					aria-label="取消（Esc）"
					title="取消（Esc）"
					onClick={e => {
						e.stopPropagation();
						cancel();
					}}
				>
					<X className="size-3.5" />
				</button>
			</div>

			<PanelCollapse open={expanded} className="xy-panel-ask-body">
				<div className="xy-panel-ask-cmd-wrap">
					<div
						ref={cmdRef}
						className={`xy-panel-ask-cmd${clipped ? ' is-clipped' : ''}`}
						style={{
							maxHeight: clipped
								? COLLAPSE_LINES * LINE_HEIGHT
								: undefined,
						}}
					>
						{prompt || `允许执行 ${toolLabel}？`}
					</div>
					{isLong ? (
						<div
							className={`xy-panel-ask-cmd-mask${clipped ? ' is-show' : ''}`}
						/>
					) : null}
				</div>

				{intent === 'choice' && isPeerThree ? (
					<div className="xy-panel-ask-actions flex-wrap gap-2">
						<button
							type="button"
							className="xy-panel-ask-reject"
							onClick={() => void decide(false, 'deny')}
						>
							硬拦
						</button>
						<button
							type="button"
							className="xy-panel-ask-reject"
							onClick={() => void decide(false, 'remind')}
						>
							提醒
						</button>
						<button
							type="button"
							className="xy-panel-ask-allow"
							onClick={() => void decide(true, 'allow')}
						>
							继续
						</button>
					</div>
				) : (
					<div className="xy-panel-ask-actions flex-wrap items-center gap-2">
						{/* 「不再询问」勾选放左侧（mr-auto 把按钮推到右侧），样式走面板主色调。 */}
						{isBashConfirm ? (
							<label className="mr-auto flex cursor-pointer select-none items-center gap-1.5 rounded-md px-1.5 py-1 text-[11px] text-ink-soft transition-colors hover:bg-line/40 hover:text-ink">
								<input
									type="checkbox"
									className="size-3.5 rounded border-line accent-[var(--xy-accent)]"
									checked={remember}
									onChange={e => setRemember(e.target.checked)}
								/>
								<span>不再询问此类命令</span>
							</label>
						) : null}
						<button
							type="button"
							className="xy-panel-ask-reject"
							onClick={() => void decide(false)}
						>
							拒绝
						</button>
						<button
							type="button"
							className="xy-panel-ask-allow"
							onClick={() =>
								void decide(true, undefined, isBashConfirm && remember)
							}
						>
							允许
						</button>
					</div>
				)}
			</PanelCollapse>
		</div>
	);
}
