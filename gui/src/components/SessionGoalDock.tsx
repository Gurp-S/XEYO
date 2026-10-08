/**
 * SessionGoalDock.tsx — goal 条带，逐条对齐 DSH 的 GoalBar
 * （packages/client/ui-goal/src/client/GoalBar.tsx + .module.css）。
 *
 * 条带上只有：glyph + 相位标签 + 单行省略的目标原文 + 图标动作
 * （active→暂停 / paused→恢复 / 编辑 / 清除；**blocked 只有编辑与清除**）。
 * 编辑是同一条原地换成输入框，失败内联在条内（role=alert）。
 *
 * 按业主 2026-10-03 深夜裁定"goal 样式、交互等所有对齐 DSH"，XEYO 这几项
 * 从条带上撤掉（DSH 没有）：自动续跑(armed)的开关与状态圆点、待确认完成的
 * 标记完成/继续、轮次上限编辑、停止本轮、受阻重开、清除的二次确认。
 *
 * 同批撤净的还有 pause/resume 的 disarm/arm 副作用：GUI 不再触碰 round-driver
 * （服务端 arm 的唯一入口是 `/goal` 后的同步与本组件，两处都已删）＝自动续跑停用。
 *
 * 数据双源不变：SSE goal 帧（turn 起点 whole-value，经 chatStore onGoal 落库）
 * + 3s 轻量轮询（settlement 发生在流结束之后，帧盖不住那段——41 号 §8）。
 * 纪律：动词 single-flight；PATCH 带 revision CAS，409 用后端当前 goal 刷新后
 * 重试一次（禁盲写）；armed 不落盘，重启后自然回到 disarmed。
 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {
	Check,
	Compass,
	Pause,
	Pencil,
	Play,
	Trash2,
	X,
} from 'lucide-react';
import {toast} from '@/lib/toast';
import {isImeComposing} from '@/lib/ime';
import {type SessionGoalState} from '@/lib/api/goals';
import {useSessionGoalLive} from '@/hooks/useSessionGoalLive';
export {useSessionGoalLive} from '@/hooks/useSessionGoalLive';
import {runGoalAction} from '@/lib/goalMutations';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {isGoalLive} from '@/lib/goalSync';
import {cn} from '@/lib/utils';
import {useChatStore} from '@/stores/chatStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {DockPresence} from './DockPresence';

/** 动词失败的统一说法：后端的原话必须带出来，否则用户只知道"按了没反应"。 */
function verbFailureText(label: string, message: string): string {
	return `${label}未生效：${message || '服务端拒绝，且未给出原因'}`;
}

type Props = {
	/** 嵌入 Composer 统一外框时不包外层 padding。 */
	embedded?: boolean;
};

export function SessionGoalDock({embedded = false}: Props) {
	const activeId = useChatStore(s => s.activeId);
	const activeSessionArchived = useChatStore(s =>
		Boolean(activeId && s.sessions.some(session => session.id === activeId && session.archived)),
	);
	const state = useChatStore(s =>
		activeId ? (s.sessionGoalById?.[activeId] ?? null) : null,
	);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const busyRef = useRef(false);
	const [pending, setPending] = useState(false);
	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState('');
	// 失败内联在条带里：条带就是动作发生的地方（DSH GoalBar 的 actionError）。
	const [actionError, setActionError] = useState<string | null>(null);
	// 清除后先本地记住这条 id：投影滞后时旧版目标不许再冒充当前事实。
	const [clearedGoalId, setClearedGoalId] = useState<string | null>(null);
	useSessionGoalLive(activeId);

	// 目标换了身份（外部清除/完成/替换）就丢掉本地编辑态：残留草稿的 Enter
	// 会写到一个新目标上（DSH GoalBar 同口径）。
	const goalId = state?.goal.goal_id;
	useEffect(() => {
		setEditing(false);
		setActionError(null);
		setClearedGoalId(null);
	}, [goalId, activeSessionArchived]);

	// 编辑态拥有 Esc（escStack LIFO 顶层）：元素级 onKeyDown 在流式期间会被
	// 「停止生成」层先吃掉 —— 实测 Esc 停了回合、编辑框不关（e2e input-chain 探针）。
	useEffect(() => {
		if (!editing) {
			return;
		}
		pushEscLayer('goal-dock-edit', () => setEditing(false));
		return () => popEscLayer('goal-dock-edit');
	}, [editing]);

	const report = useCallback((label: string, message: string) => {
		setActionError(verbFailureText(label, message));
	}, []);

	if (!activeId || !isGoalLive(state)) {
		return null;
	}
	const {goal} = state;
	if (goal.goal_id === clearedGoalId) {
		return null;
	}

	const title = goal.title.trim() || '未命名目标';
	const blocked = goal.status === 'blocked';
	const paused = goal.status === 'paused';

	const act = (fn: () => Promise<unknown>) => {
		if (busyRef.current) return;
		busyRef.current = true;
		setPending(true);
		setActionError(null);
		void fn().finally(() => {
			busyRef.current = false;
			setPending(false);
		});
	};
	/** 归档只读：DSH 没这个态，但 XEYO 的写请求会被后端挡，先在前端说清楚。 */
	const archivedGuard = () => {
		if (!activeSessionArchived) return true;
		toast.info('归档对话为只读，请先恢复');
		return false;
	};
	const pauseGoal = () =>
		act(async () => {
			const res = await runGoalAction(activeId, 'pause', {goal_id: goal.goal_id});
			if (res && !res.ok) report('目标操作', res.message);
		});
	const resumeGoal = () =>
		act(async () => {
			const res = await runGoalAction(activeId, 'resume', {goal_id: goal.goal_id});
			if (res && !res.ok) report('目标操作', res.message);
		});

	const saveEdit = () =>
		act(async () => {
			const text = draft.trim();
			if (text === '') return;
			const res = await runGoalAction(activeId, 'edit', {goal_id: goal.goal_id, text});
			if (!res) return;
			if (!res.ok) {
				// 只在真的改成了才收编辑器：否则用户刚输入的标题会跟着一起消失。
				report('目标操作', res.message);
				return;
			}
			setEditing(false);
		});
	const clearGoal = () =>
		act(async () => {
			const clearedId = goal.goal_id;
			const res = await runGoalAction(activeId, 'drop', {goal_id: goal.goal_id});
			if (res && !res.ok) {
				report('目标操作', res.message);
				return;
			}
			if (res?.ok) setClearedGoalId(clearedId);
		});

	const phaseLabel = paused ? '已暂停的目标' : blocked ? '受阻的目标' : '进行中的目标';
	const objective = (goal.text.trim() || title).slice(0, 140);

	const iconBtn =
		'xy-icon-btn inline-flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-full text-mute transition-colors hover:bg-paper-deep hover:text-ink disabled:opacity-40 disabled:hover:bg-transparent';
	const disabledTitle = activeSessionArchived ? '归档对话为只读，请先恢复' : undefined;

	const actions = (
		<div className="flex shrink-0 items-center gap-[10px]">
			{goal.status === 'active' ? (
				<button
					type="button"
					className={iconBtn}
					aria-label="暂停"
					title={disabledTitle ?? '暂停目标'}
					disabled={pending || activeSessionArchived}
					onClick={() => {
						if (!archivedGuard()) return;
						pauseGoal();
					}}
				>
					<Pause className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
				</button>
			) : paused ? (
				<button
					type="button"
					className={iconBtn}
					aria-label="恢复"
					title={disabledTitle ?? '恢复目标'}
					disabled={pending || activeSessionArchived}
					onClick={() => {
						if (!archivedGuard()) return;
						resumeGoal();
					}}
				>
					<Play className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
				</button>
			) : null}
			<button
				type="button"
				className={iconBtn}
				aria-label="编辑目标"
				title={disabledTitle ?? '编辑目标'}
				disabled={pending || activeSessionArchived}
				onClick={() => {
					if (!archivedGuard()) return;
					const g = useChatStore.getState().sessionGoalById?.[activeId]?.goal;
					setDraft(g?.text || g?.title || '');
					setActionError(null);
					setEditing(true);
				}}
			>
				<Pencil className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
			</button>
			<button
				type="button"
				className={iconBtn}
				aria-label="清除目标"
				title={disabledTitle ?? '清除目标'}
				disabled={pending || activeSessionArchived}
				onClick={() => {
					if (!archivedGuard()) return;
					clearGoal();
				}}
			>
				<Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
			</button>
		</div>
	);

	const panel = (
		<div
			className="xy-panel-ask xy-goal-dock is-expanded"
			role="region"
			aria-label="Session goal"
			data-goal-bar=""
			title={blocked ? goal.blocked_reason || undefined : undefined}
		>
			{editing ? (
				/* 编辑态：整条换位，不另起一块面板（DSH GoalBar 的 inline form）。 */
				<div className="flex h-9 items-center gap-[10px] px-3">
					<input
						value={draft}
						onChange={e => setDraft(e.target.value)}
						placeholder="目标内容"
						autoFocus
						aria-label="目标内容"
						onKeyDown={e => {
							if (isImeComposing(e.nativeEvent)) return;
							if (e.key === 'Enter') void saveEdit();
							if (e.key === 'Escape') setEditing(false);
						}}
						className="min-w-0 flex-1 rounded-md border border-line/70 bg-paper-deep/40 px-2 text-[13px] leading-5 text-ink outline-none focus:border-accent/60"
					/>
					{actionError !== null ? (
						<span className="min-w-0 shrink truncate text-[12px] leading-5 text-danger" role="alert">
							{actionError}
						</span>
					) : null}
					<div className="flex shrink-0 items-center gap-[10px]">
						<button
							type="button"
							className={iconBtn}
							aria-label="保存目标"
							title="保存目标"
							disabled={pending || draft.trim() === ''}
							onClick={() => void saveEdit()}
						>
							<Check className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
						</button>
						<button
							type="button"
							className={iconBtn}
							aria-label="取消编辑"
							title="取消编辑"
							disabled={pending}
							onClick={() => setEditing(false)}
						>
							<X className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
						</button>
					</div>
				</div>
			) : (
				<div className="flex h-9 items-center gap-[10px] pl-3 pr-[5px]">
					<span className="shrink-0 text-mute" aria-hidden>
						<Compass className="h-3.5 w-3.5" strokeWidth={1.9} />
					</span>
					<span
						className={cn(
							'shrink-0 text-[13px] font-medium leading-6',
							blocked ? 'text-warn' : 'text-ink',
						)}
					>
						{phaseLabel}
					</span>
					<span className="min-w-0 flex-1 truncate text-[13px] leading-5 text-ink-soft">
						{objective}
					</span>
					{actionError !== null ? (
						<span className="min-w-0 shrink truncate text-[12px] leading-5 text-danger" role="alert">
							{actionError}
						</span>
					) : null}
					{actions}
				</div>
			)}
		</div>
	);

	return (
		<DockPresence open smoothness={smoothness}>
			{embedded ? (
				panel
			) : (
				<div className="shrink-0 px-3 pt-1 sm:px-5">
					<div className="mx-auto w-full max-w-3xl">{panel}</div>
				</div>
			)}
		</DockPresence>
	);
}

/** live 谓词（供 hook 与测试共用）：唯一权威在 lib/goalSync 的 isGoalLive。 */
export function goalDockLiveFor(
	state: SessionGoalState | null | undefined,
): boolean {
	return isGoalLive(state);
}

/** Goal 面板是否应在 Composer 统一外框中显示（参与外框融合高度）。 */
export function useSessionGoalDockLive(): boolean {
	const activeId = useChatStore(s => s.activeId);
	const state = useChatStore(s =>
		activeId ? (s.sessionGoalById?.[activeId] ?? null) : null,
	);
	return Boolean(activeId) && goalDockLiveFor(state);
}
