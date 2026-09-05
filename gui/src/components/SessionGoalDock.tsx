/**
 * SessionGoalDock.tsx — 41 号 P0（对齐 DSH GoalBar 外观，保留 XEYO 半透明）。
 *
 * 对齐 dsh-client-ui-goal（client.js GoalBar）：单行 bar = 目标图标 + 阶段标签 +
 * 截断目标 + 右侧动作（暂停/恢复/编辑/清除），编辑为行内 input，clear 带确认。
 * XEYO 有意保留的差异（§9.4）：
 * - 投影携带 armed 态 → 条带以圆点标注「已开启自动续跑 vs 空闲」（DSH 做不到）。
 * - 额外暴露 XEYO 的候选（pending_complete）「待确认完成 + 标记完成/继续」与
 *   blocked 的「恢复」。
 * 渲染规则：无 goal / completed / abandoned 不渲染；active / paused / blocked /
 * pending_complete 渲染。
 *
 * 数据双源：SSE goal 帧（turn 起点 whole-value，经 chatStore onGoal 落库）+
 * 3s 轻量轮询（settlement 发生在流结束之后，帧盖不住那段——轮询补齐，41 号 §8）。
 * 纪律：动词 single-flight；PATCH 带 revision CAS，409 用后端当前 goal 刷新后
 * 重试一次（禁盲写）； armed 不落盘，重启后自然回到 disarmed。
 */
import {useEffect, useRef, useState} from 'react';
import {
	Pause,
	Pencil,
	Play,
	Square,
	Target,
	Trash2,
} from 'lucide-react';
import type {ReactNode} from 'react';
import {interruptChat} from '@/lib/api';
import {
	fetchGoal,
	patchGoalAction,
	roundDriverAction,
	type GoalMutationResult,
	type SessionGoalState,
} from '@/lib/api/goals';
import {cn} from '@/lib/utils';
import {useChatStore} from '@/stores/chatStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {DockPresence} from './DockPresence';

const GOAL_POLL_MS = 3000;

/** whole-value 写回 store（SSE 帧与 GET/动词响应共用同形）。 */
function writeGoalState(sessionId: string, state: SessionGoalState | null) {
	useChatStore.setState(s => ({
		sessionGoalById: {...s.sessionGoalById, [sessionId]: state},
	}));
}

/**
 * 41 号 P0 轻量轮询：可见时每 3s GET 投影并 whole-value 覆写。
 * 只在挂载的 Dock 内运行；不可见 / 在途时跳过，绝不阻塞 UI。
 */
export function useSessionGoalLive(sessionId: string | null) {
	const inflight = useRef(false);
	useEffect(() => {
		if (!sessionId) return;
		let stopped = false;
		const refresh = async () => {
			if (inflight.current || document.visibilityState !== 'visible') {
				return;
			}
			inflight.current = true;
			try {
				const {goal, driver} = await fetchGoal(sessionId);
				if (!stopped) {
					writeGoalState(sessionId, goal ? {goal, driver} : null);
				}
			} catch {
				/* 降级：下个周期再试 */
			} finally {
				inflight.current = false;
			}
		};
		void refresh();
		const timer = window.setInterval(() => {
			void refresh();
		}, GOAL_POLL_MS);
		return () => {
			stopped = true;
			window.clearInterval(timer);
		};
	}, [sessionId]);
}

/** PATCH 动词执行：CAS 409 → 用后端附带的当前 goal 刷新，重试一次（禁盲写）。 */
async function runGoalVerb(
	sessionId: string,
	run: (revision: number) => Promise<GoalMutationResult>,
): Promise<void> {
	const cur = useChatStore.getState().sessionGoalById?.[sessionId] ?? null;
	if (!cur) return;
	let res = await run(cur.goal.revision);
	if (!res.ok && res.conflict) {
		writeGoalState(sessionId, {goal: res.conflict, driver: cur.driver});
		res = await run(res.conflict.revision);
	}
	if (res.ok) {
		writeGoalState(
			sessionId,
			res.goal ? {goal: res.goal, driver: res.driver ?? cur.driver} : null,
		);
	}
}

type Props = {
	/** 嵌入 Composer 统一外框时不包外层 padding。 */
	embedded?: boolean;
};

export function SessionGoalDock({embedded = false}: Props) {
	const activeId = useChatStore(s => s.activeId);
	const state = useChatStore(s =>
		activeId ? (s.sessionGoalById?.[activeId] ?? null) : null,
	);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const busyRef = useRef(false);
	const [editing, setEditing] = useState(false);
	const [confirmDrop, setConfirmDrop] = useState(false);
	const [editTitle, setEditTitle] = useState('');
	const [editMax, setEditMax] = useState('');
	useSessionGoalLive(activeId);

	// 编辑 / 删除确认卡：点卡外或 Esc 关闭。
	useEffect(() => {
		if (!editing && !confirmDrop) return;
		const onDoc = (e: MouseEvent) => {
			const t = e.target as HTMLElement;
			if (t.closest('[data-goal-pop]')) return;
			setEditing(false);
			setConfirmDrop(false);
		};
		pushEscLayer('goal-pop', () => {
			setEditing(false);
			setConfirmDrop(false);
		});
		document.addEventListener('mousedown', onDoc);
		return () => {
			document.removeEventListener('mousedown', onDoc);
			popEscLayer('goal-pop');
		};
	}, [editing, confirmDrop]);

	// 切换会话时关闭弹层。
	useEffect(() => {
		setEditing(false);
		setConfirmDrop(false);
	}, [activeId]);

	if (!activeId || !state) {
		return null;
	}
	const {goal, driver} = state;
	if (
		goal.status !== 'active' &&
		goal.status !== 'paused' &&
		goal.status !== 'blocked'
	) {
		return null;
	}

	const armed = driver?.activation === 'armed';
	const inRound = Array.isArray(driver?.active_round);
	const title = goal.title.trim() || '未命名目标';
	const blocked = goal.status === 'blocked';
	const paused = goal.status === 'paused';
	const pending = goal.status === 'active' && goal.pending_complete === true;

	const act = (fn: () => Promise<unknown>) => {
		if (busyRef.current) return;
		busyRef.current = true;
		void fn().finally(() => {
			busyRef.current = false;
		});
	};

	const arm = () =>
		act(async () => {
			const res = await roundDriverAction(activeId, 'arm');
			if (res.ok) {
				writeGoalState(
					activeId,
					res.goal ? {goal: res.goal, driver: res.driver} : null,
				);
			}
		});
	const doDisarm = async () => {
		const res = await roundDriverAction(activeId, 'disarm');
		if (res.ok) {
			writeGoalState(
				activeId,
				res.goal ? {goal: res.goal, driver: res.driver} : null,
			);
		}
	};
	/** 停止：轮中 = 现有 Stop（interrupt）→ settlement 自动 disarm；预约期 = 仅 disarm。 */
	const stop = () =>
		act(async () => {
			if (inRound) {
				try {
					await interruptChat(activeId);
				} catch {
					/* interrupt 失败不阻断 disarm */
				}
			}
			await doDisarm();
		});
	const pauseGoal = () =>
		act(async () => {
			await runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'pause', {revision: rev}),
			);
			// 暂停后停掉自动续跑（paused 不续跑；语义对齐 DSH pause）。
			if (armed) {
				await doDisarm();
			}
		});
	const resumeGoal = () =>
		act(async () => {
			await runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'resume', {revision: rev}),
			);
			// 恢复即重新 armed（对齐 DSH「resume re-arms」）。
			const res = await roundDriverAction(activeId, 'arm');
			if (res.ok) {
				writeGoalState(
					activeId,
					res.goal ? {goal: res.goal, driver: res.driver} : null,
				);
			}
		});
	const reopen = () =>
		act(() =>
			runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'reopen', {revision: rev}),
			),
		);
	const confirmComplete = () =>
		act(() =>
			runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'confirm_complete', {revision: rev}),
			),
		);
	const continueGoal = () =>
		act(() =>
			runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'continue', {revision: rev}),
			),
		);

	const openEdit = () => {
		const g = useChatStore.getState().sessionGoalById?.[activeId]?.goal;
		setEditTitle(g?.text || g?.title || '');
		setEditMax(g && g.max_rounds > 0 ? String(g.max_rounds) : '');
		setConfirmDrop(false);
		setEditing(true);
	};
	const saveEdit = () =>
		act(async () => {
			const text = editTitle.trim() || goal.text.trim();
			await runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'edit', {
					revision: rev,
					text,
					maxRounds: editMax.trim()
						? Number(editMax.trim())
						: undefined,
				}),
			);
			setEditing(false);
		});
	const dropGoal = () =>
		act(async () => {
			await runGoalVerb(activeId, rev =>
				patchGoalAction(activeId, 'drop', {revision: rev}),
			);
			setConfirmDrop(false);
		});

	const pillBtn =
		'xy-press inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-sans text-[11px] leading-tight text-ink transition-colors disabled:opacity-50';
	const ghostBtn = cn(pillBtn, 'border-line/70 bg-paper hover:bg-paper-deep/50');
	const accentBtn = cn(pillBtn, 'border-accent/60 bg-accent/10 text-accent hover:bg-accent/20');
	const iconBtnCls =
		'xy-icon-btn inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-mute transition-colors hover:bg-paper-deep hover:text-ink disabled:opacity-40';

	// DSH 阶段标签
	const phaseLabel = paused
		? '已暂停的目标'
		: blocked
			? '受阻的目标'
			: pending
				? '待确认完成'
				: '进行中的目标';
	const objective = (goal.text.trim() || title).slice(0, 140);
	const armedDot =
		!paused && !blocked && !pending ? (
			<span
				className={cn(
					'size-2 shrink-0 rounded-full',
					armed ? 'bg-ok animate-pulse' : 'bg-mute/50',
				)}
				aria-hidden
			/>
		) : null;

	const editBtn = (
		<button
			type="button"
			className={iconBtnCls}
			aria-label="编辑目标"
			title="编辑目标"
			onClick={openEdit}
		>
			<Pencil className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
		</button>
	);
	const clearBtn = (
		<button
			type="button"
			className={iconBtnCls}
			aria-label="清除目标"
			title="清除目标"
			onClick={() => {
				setEditing(false);
				setConfirmDrop(true);
			}}
		>
			<Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
		</button>
	);

	let primary: ReactNode;
	if (paused) {
		primary = (
			<button type="button" className={accentBtn} onClick={resumeGoal}>
				<Play className="mr-0.5 inline size-2.5" strokeWidth={2} aria-hidden />
				恢复
			</button>
		);
	} else if (blocked) {
		primary = (
			<button type="button" className={accentBtn} onClick={reopen}>
				<Play className="mr-0.5 inline size-2.5" strokeWidth={2} aria-hidden />
				恢复
			</button>
		);
	} else if (pending) {
		primary = (
			<>
				<button type="button" className={accentBtn} onClick={confirmComplete}>
					标记完成
				</button>
				<button type="button" className={ghostBtn} onClick={continueGoal}>
					继续此目标
				</button>
			</>
		);
	} else if (inRound) {
		primary = (
			<button type="button" className={ghostBtn} onClick={stop}>
				<Square className="mr-0.5 inline size-2.5" strokeWidth={2} aria-hidden />
				停止
			</button>
		);
	} else if (armed) {
		primary = (
			<button
				type="button"
				className={ghostBtn}
				title="暂停目标（持久，停止自动续跑）"
				onClick={pauseGoal}
			>
				<Pause className="mr-0.5 inline size-2.5" strokeWidth={2} aria-hidden />
				暂停
			</button>
		);
	} else {
		primary = (
			<button type="button" className={accentBtn} onClick={arm}>
				<Play className="mr-0.5 inline size-2.5" strokeWidth={2} aria-hidden />
				自动续跑
			</button>
		);
	}

	const panel = (
		<div className="xy-panel-ask is-expanded" role="region" aria-label="Session goal">
			<div className="flex items-center gap-2 px-3 py-1.5">
				<Target className="size-4 shrink-0 text-mute" strokeWidth={1.8} aria-hidden />
				{armedDot}
				<span
					className={cn(
						'shrink-0 text-[12px] font-medium text-ink',
						blocked && 'text-warn',
						pending && 'text-ok',
					)}
				>
					{phaseLabel}
				</span>
				<span className="min-w-0 flex-1 truncate text-[12px] text-ink-soft">
					{objective}
				</span>
				<div className="ml-auto flex shrink-0 items-center gap-1">
					{primary}
					{editBtn}
					{clearBtn}
				</div>
			</div>

			{editing ? (
				<div className="flex items-center gap-2 px-3 pb-2" data-goal-pop>
					<input
						value={editTitle}
						onChange={e => setEditTitle(e.target.value)}
						placeholder="目标内容"
						autoFocus
						onKeyDown={e => {
							if (e.key === 'Enter') void saveEdit();
							if (e.key === 'Escape') setEditing(false);
						}}
						className="min-w-0 flex-1 rounded-md border border-line/70 bg-paper-deep/40 px-2 py-1 text-[12px] text-ink outline-none focus:border-accent/60"
					/>
					<input
						value={editMax}
						onChange={e => setEditMax(e.target.value)}
						inputMode="numeric"
						placeholder="轮次上限(0=默认)"
						className="w-24 rounded-md border border-line/70 bg-paper-deep/40 px-2 py-1 text-[12px] text-ink outline-none focus:border-accent/60"
					/>
					<button type="button" className={accentBtn} onClick={() => void saveEdit()}>
						保存
					</button>
					<button type="button" className={ghostBtn} onClick={() => setEditing(false)}>
						取消
					</button>
				</div>
			) : null}

			{confirmDrop ? (
				<div className="px-3 pb-2" data-goal-pop>
					<p className="text-[11px] text-ink">删除这个目标？该会话将不再显示目标面板。</p>
					<div className="mt-1.5 flex justify-end gap-1">
						<button type="button" className={ghostBtn} onClick={() => setConfirmDrop(false)}>
							取消
						</button>
						<button
							type="button"
							className="xy-press rounded-md border border-warn/60 bg-warn/10 px-2 py-0.5 font-sans text-[11px] leading-tight text-warn hover:bg-warn/20"
							onClick={dropGoal}
						>
							确认删除
						</button>
					</div>
				</div>
			) : null}
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

/** live 谓词（纯函数，供 hook 与测试共用）：active / paused / blocked 即 live。 */
export function goalDockLiveFor(
	state: SessionGoalState | null | undefined,
): boolean {
	if (!state) return false;
	const {goal} = state;
	return (
		goal.status === 'active' ||
		goal.status === 'paused' ||
		goal.status === 'blocked'
	);
}

/** Goal 面板是否应在 Composer 统一外框中显示（参与外框融合高度）。 */
export function useSessionGoalDockLive(): boolean {
	const activeId = useChatStore(s => s.activeId);
	const state = useChatStore(s =>
		activeId ? (s.sessionGoalById?.[activeId] ?? null) : null,
	);
	return Boolean(activeId) && goalDockLiveFor(state);
}
