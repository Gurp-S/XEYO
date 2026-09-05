import {RollbackDiffTree} from '@/components/RollbackDiffTree';
import {buildRollbackDiffTree, classifyRollbackOperation} from '@/lib/rollbackDiffTree';
import {type RollbackOperation, type RollbackPlan} from '@/lib/types';
import {cn} from '@/lib/utils';
import {AlertTriangle, CornerDownLeft, RotateCcw, X} from 'lucide-react';
import {useEffect, useMemo, useRef, useState} from 'react';
import {setCheckpointAnchor} from '@/lib/api';
import {toast} from '@/lib/toast';
import {useRewindV3Store} from '@/stores/rewindV3Store';

export function WorkspaceRevertDialog({
	plan,
	mode = 'confirm',
	error,
	editedText,
	onConfirm,
	onCancel,
	onRetryResend,
	onRetryCheckpoint,
	onAbandonRecovery,
	confirming = false,
}: {
	plan?: RollbackPlan;
	mode?: 'confirm' | 'resend' | 'recovery' | 'blocked';
	error?: string | null;
	editedText?: string | null;
	onConfirm?: (opts: {restoreWorkspace: boolean}) => void;
	onCancel: () => void;
	onRetryResend?: () => void;
	onRetryCheckpoint?: () => void;
	onAbandonRecovery?: () => void;
	confirming?: boolean;
}) {
	const dialogRef = useRef<HTMLDialogElement>(null);
	const isResend = mode === 'resend';
	const isRecovery = mode === 'recovery';
	const isBlocked = mode === 'blocked';
	const isSimpleConfirm = mode === 'confirm';
	const metadata = plan?.metadata;
	const operations = Array.isArray(metadata?.operations) ? metadata.operations : [];
	const workspaceRoot =
		typeof metadata?.workspace_root === 'string'
			? metadata.workspace_root
			: undefined;

	const rollbackOps = useMemo(
		() =>
			operations.filter(
				(op): op is RollbackOperation =>
					typeof op === 'object' &&
					op !== null &&
					classifyRollbackOperation(op) !== null,
			),
		[operations],
	);
	const hasTargetCommit = Boolean(
		typeof metadata?.target_commit === 'string' && metadata.target_commit.trim(),
	);
	const restoresFlag = metadata?.restores_workspace === true;
	const canRestoreWorkspace =
		restoresFlag || rollbackOps.length > 0 || hasTargetCommit;

	const diffTree = useMemo(
		() => buildRollbackDiffTree(rollbackOps, workspaceRoot),
		[rollbackOps, workspaceRoot],
	);

	useEffect(() => {
		const el = dialogRef.current;
		if (el && !el.open) {
			el.showModal();
		}
		return () => {
			if (el?.open) {
				el.close();
			}
		};
	}, []);

	useEffect(() => {
		if (!isSimpleConfirm || confirming) {
			return;
		}
		const onKey = (event: KeyboardEvent) => {
			if (event.key === 'Enter' && !event.isComposing) {
				event.preventDefault();
				onConfirm?.({restoreWorkspace: canRestoreWorkspace});
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [canRestoreWorkspace, confirming, isSimpleConfirm, onConfirm]);

	/* 历史气泡发送：简约确认（对齐 Cursor checkpoint 弹窗） */
	if (isSimpleConfirm) {
		return (
			<dialog
				ref={dialogRef}
				className="xy-rewind-dialog xy-rewind-dialog-simple xy-modal-panel xy-modal-elevated m-auto overflow-hidden rounded-xl border border-line/50 bg-paper p-0 shadow-none backdrop:bg-black/45 backdrop:backdrop-blur-md open:animate-in open:fade-in open:zoom-in-95"
				onCancel={event => {
					event.preventDefault();
					onCancel();
				}}
			>
				<div className="relative px-4 pb-3 pt-4">
					<button
						type="button"
						onClick={onCancel}
						disabled={confirming}
						className="absolute right-3 top-3 rounded-md p-1 text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40"
						aria-label="关闭"
					>
						<X className="h-3.5 w-3.5" strokeWidth={2.25} />
					</button>
					<h2 className="pr-7 font-sans text-[14px] font-semibold leading-snug text-ink">
						确定要回溯到这个对话吗
					</h2>
					<p className="mt-1.5 text-[12px] leading-relaxed text-mute">
						你可以随时恢复
					</p>
				</div>
				<div className="flex items-center justify-end gap-2 px-4 pb-4">
					<button
						type="button"
						onClick={onCancel}
						disabled={confirming}
						className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40"
					>
						取消
					</button>
					<button
						type="button"
						onClick={() =>
							onConfirm?.({restoreWorkspace: canRestoreWorkspace})
						}
						disabled={confirming}
						className="inline-flex items-center gap-1.5 rounded-lg border-none bg-accent px-3 py-1.5 font-sans text-[12px] font-semibold text-on-accent transition-colors hover:bg-accent-hover disabled:opacity-60"
					>
						{confirming ? '正在继续…' : '继续'}
						{!confirming ? (
							<CornerDownLeft
								className="h-3 w-3 opacity-80"
								strokeWidth={2.5}
								aria-hidden
							/>
						) : null}
					</button>
				</div>
			</dialog>
		);
	}

	return (
		<dialog
			ref={dialogRef}
			className="xy-rewind-dialog xy-modal-panel xy-modal-elevated m-auto flex flex-col overflow-hidden rounded-2xl border border-line/60 bg-paper p-0 shadow-none backdrop:bg-black/45 backdrop:backdrop-blur-md open:animate-in open:fade-in open:zoom-in-95"
			onCancel={event => {
				event.preventDefault();
				onCancel();
			}}
		>
			<div className="shrink-0 border-b border-line/40 px-4 py-3">
				<div className="flex items-center gap-2.5">
					<span
						className={cn(
							'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ring-1',
							isResend || isRecovery
								? 'bg-accent/10 text-accent ring-accent/20'
								: 'bg-warn/10 text-warn ring-warn/15',
						)}
					>
						<RotateCcw className="h-3.5 w-3.5" strokeWidth={2.25} />
					</span>
					<div className="min-w-0 flex-1">
						<h2 className="font-sans text-[13px] font-semibold text-ink">
							{isBlocked
								? '无法回滚工作区'
								: isRecovery
									? '回溯需要恢复'
									: '编辑内容已放回输入框'}
						</h2>
						{isRecovery ? (
							<p className="mt-0.5 text-[10px] leading-snug text-mute">
								对话可能已截断，工作区文件可能尚未恢复。可从检查点恢复文件，或放弃并保留当前磁盘内容。
							</p>
						) : null}
						{isBlocked ? (
							<p className="mt-0.5 text-[10px] leading-snug text-mute">
								存在冲突，不会覆盖你手动改过的文件。请先处理冲突后再回溯。
							</p>
						) : null}
					</div>
				</div>
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
				{isRecovery ? (
					<div className="space-y-2 text-[11px] leading-relaxed text-ink-soft">
						<p>
							请勿再次点「确认回滚」——重复执行可能二次破坏。先处理本次恢复。
						</p>
						{error ? (
							<p className="rounded-lg border border-line/50 bg-paper-deep/40 px-2.5 py-2 text-[10px] text-mute">
								{error}
							</p>
						) : null}
					</div>
				) : isResend ? (
					<div className="space-y-2 text-[11px] leading-relaxed text-ink-soft">
						<p>回溯已完成，请重新发送编辑后的消息以继续对话。</p>
						{editedText?.trim() ? (
							<div className="rounded-lg border border-line/50 bg-paper-deep/40 px-2.5 py-2">
								<p className="mb-1 text-[10px] text-mute">将发送的内容</p>
								<p className="max-h-28 overflow-y-auto whitespace-pre-wrap text-[12px] text-ink">
									{editedText.trim()}
								</p>
							</div>
						) : null}
						{error ? (
							<p className="text-[10px] text-mute">{error}</p>
						) : null}
					</div>
				) : isBlocked && plan ? (
					<div className="space-y-3">
						{canRestoreWorkspace ? (
							<RollbackDiffTree nodes={diffTree} />
						) : null}
						{error ? (
							<p className="text-[10px] text-mute">{error}</p>
						) : null}
					</div>
				) : null}
			</div>

			<div className="shrink-0 border-t border-line/40 bg-paper-deep/30 px-4 py-3">
				{isResend ? (
					<div className="mb-3 flex items-start gap-1.5 text-[10px] leading-relaxed text-mute">
						<AlertTriangle
							className="mt-px h-3 w-3 shrink-0 text-warn/90"
							strokeWidth={2.25}
						/>
						<p>工作区已回溯。编辑内容已放回输入框，由你决定是否发送，不会自动发出。</p>
					</div>
				) : isBlocked ? (
					<div className="mb-3 flex items-start gap-1.5 text-[10px] leading-relaxed text-mute">
						<AlertTriangle
							className="mt-px h-3 w-3 shrink-0 text-warn/90"
							strokeWidth={2.25}
						/>
						<p>{error || '存在冲突，已阻止覆盖。'}</p>
					</div>
				) : null}

				<div className="flex flex-wrap justify-end gap-2">
					{isRecovery ? (
						<>
							<button
								type="button"
								onClick={onAbandonRecovery}
								disabled={confirming}
								className="xy-panel-ask-reject px-4 py-1.5 text-[12px] disabled:opacity-50"
							>
								放弃并保留文件
							</button>
							<button
								type="button"
								onClick={onRetryCheckpoint}
								disabled={confirming}
								className="rounded-full border-none bg-warn px-4 py-1.5 font-sans text-[12px] font-semibold text-white transition-colors hover:bg-[color-mix(in_srgb,var(--xy-warn)_88%,black)] disabled:opacity-60"
							>
								{confirming ? '正在恢复…' : '从检查点恢复'}
							</button>
						</>
					) : isBlocked ? (
						<button
							type="button"
							onClick={onCancel}
							className="xy-panel-ask-allow px-4 py-1.5 text-[12px]"
						>
							知道了
						</button>
					) : (
						<>
							<button
								type="button"
								onClick={onCancel}
								className="xy-panel-ask-reject px-4 py-1.5 text-[12px]"
							>
								取消
							</button>
							<button
								type="button"
								onClick={onRetryResend}
								disabled={confirming}
								className="xy-panel-ask-allow px-4 py-1.5 text-[12px] disabled:opacity-50"
							>
								{confirming ? '正在发送…' : '放入输入框并关闭'}
							</button>
						</>
					)}
				</div>
			</div>
		</dialog>
	);
}


/* ------------------------------------------------------------------ */
/* 回溯 v3 热路径弹窗（合同 docs/设计/31：双动作 + 完成/Undo 生命周期）   */

export function RewindV3Dialog({sessionId}: {sessionId: string}) {
	const state = useRewindV3Store(s => s.bySession[sessionId]);
	const confirmAction = useRewindV3Store(s => s.confirm);
	const undoLast = useRewindV3Store(s => s.undoLast);
	const retry = useRewindV3Store(s => s.retry);
	const retryResend = useRewindV3Store(s => s.retryResend);
	const recover = useRewindV3Store(s => s.recover);
	const abandon = useRewindV3Store(s => s.abandon);
	const close = useRewindV3Store(s => s.closeDialog);
	const dialogRef = useRef<HTMLDialogElement>(null);
	const [undoing, setUndoing] = useState(false);
	const [markingAnchor, setMarkingAnchor] = useState(false);
	const [anchorOn, setAnchorOn] = useState<boolean | null>(null);

	useEffect(() => {
		setAnchorOn(state?.checkpointAnchor ?? null);
	}, [state?.checkpointAnchor]);

	const markAnchor = async () => {
		if (!state?.targetMessageId || markingAnchor) {
			return;
		}
		const next = !(state.checkpointAnchor ?? false);
		setMarkingAnchor(true);
		try {
			const ok = await setCheckpointAnchor(sessionId, state.targetMessageId, next);
			if (ok) {
				toast.success(next ? '已标记为锚点（此检查点会被保留）' : '已取消锚点');
				// 更新已读锚点状态，按钮随之切换。
				setAnchorOn(next);
			} else {
				toast.error('更新锚点失败');
			}
		} finally {
			setMarkingAnchor(false);
		}
	};

	useEffect(() => {
		const el = dialogRef.current;
		if (state && state.phase !== 'idle') {
			if (el && !el.open) {
				el.showModal();
			}
		}
		return () => {
			if (el?.open) {
				el.close();
			}
		};
	}, [state?.phase, state === undefined]);

	if (!state || state.phase === 'idle') {
		return null;
	}
	const running = state.phase === 'running';
	const isDone = state.phase === 'done';
	const isContinue = state.action === 'continue';
	const restoreDisabled = state.checkpointState !== 'ready';

	return (
		<dialog
			ref={dialogRef}
			className="xy-rewind-dialog xy-rewind-dialog-simple xy-modal-panel xy-modal-elevated m-auto overflow-hidden rounded-xl border border-line/50 bg-paper p-0 shadow-none backdrop:bg-black/45 backdrop:backdrop-blur-md open:animate-in open:fade-in open:zoom-in-95"
			onCancel={event => {
				event.preventDefault();
				if (!running) {
					close(sessionId);
				}
			}}
		>
			<div className="relative px-4 pb-3 pt-4">
				{!running ? (
					<button
						type="button"
						onClick={() => close(sessionId)}
						className="absolute right-3 top-3 rounded-md p-1 text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink"
						aria-label="关闭"
					>
						<X className="h-3.5 w-3.5" strokeWidth={2.25} />
					</button>
				) : null}
				<h2 className="pr-7 font-sans text-[14px] font-semibold leading-snug text-ink">
					{isDone
						? '回溯完成'
						: running
							? isContinue
								? '正在回溯并重新发送…'
								: '正在恢复文件检查点…'
							: state.pillRewindId
								? '恢复这次截断？'
								: '回溯到这条对话'}
				</h2>
				<p className="mt-1.5 text-[12px] leading-relaxed text-mute">
					{isDone
						? (state.summary ?? '已完成')
						: running
							? '对话已截断，文件正在后台恢复。'
							: '对话将回到这条消息发出之前；你手动改过的文件不会被覆盖。'}
				</p>
			</div>

			{state.phase === 'dialog' && state.pillRewindId ? (
				<div className="flex flex-wrap items-center justify-end gap-2 px-4 pb-4">
					<button
						type="button"
						onClick={() => close(sessionId)}
						className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink"
					>
						取消
					</button>
					<button
						type="button"
						onClick={async () => {
							await undoLast(sessionId);
							close(sessionId);
						}}
						disabled={running}
						className="inline-flex items-center gap-1.5 rounded-lg border border-line/60 px-3 py-1.5 font-sans text-[12px] text-ink transition-colors hover:bg-ink/[0.06] disabled:opacity-40"
					>
						恢复被截断的对话
					</button>
					<button
						type="button"
						onClick={() => void confirmAction(sessionId, 'restore')}
						disabled={running || restoreDisabled}
						title={restoreDisabled ? '该切点没有文件检查点' : undefined}
						className="inline-flex items-center gap-1.5 rounded-lg border-none bg-accent px-3 py-1.5 font-sans text-[12px] font-semibold text-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
					>
						<RotateCcw className="h-3 w-3 opacity-80" strokeWidth={2.5} />
						恢复文件检查点
					</button>
				</div>
			) : null}

			{state.phase === 'dialog' && !state.pillRewindId ? (
				<div className="flex flex-wrap items-center justify-end gap-2 px-4 pb-4">
					{state.targetMessageId ? (
						<button
							type="button"
							onClick={() => void markAnchor()}
							disabled={running || markingAnchor}
							className="mr-auto rounded-lg px-3 py-1.5 font-sans text-[12px] text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40"
							title={
								anchorOn
									? '取消锚点后，此检查点可能被 GC 回收'
									: '把这条消息的检查点标记为锚点，GC 永不回收'
							}
						>
							{markingAnchor
								? '更新中…'
								: anchorOn
									? '取消锚点'
									: '标记为锚点'}
						</button>
					) : null}
					<button
						type="button"
						onClick={() => close(sessionId)}
						className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink"
					>
						取消
					</button>
					<button
						type="button"
						onClick={() => void confirmAction(sessionId, 'restore')}
						disabled={running}
						title={
							restoreDisabled
								? '此条没有文件检查点，无法恢复文件'
								: undefined
						}
						className="inline-flex items-center gap-1.5 rounded-lg border border-line/60 px-3 py-1.5 font-sans text-[12px] text-ink transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
					>
						<RotateCcw className="h-3 w-3 opacity-80" strokeWidth={2.5} />
						恢复文件检查点
					</button>
					<button
						type="button"
						onClick={() => void confirmAction(sessionId, 'continue')}
						disabled={running}
						className="inline-flex items-center gap-1.5 rounded-lg border-none bg-accent px-3 py-1.5 font-sans text-[12px] font-semibold text-on-accent transition-colors hover:bg-accent-hover disabled:opacity-60"
					>
						<CornerDownLeft className="h-3 w-3 opacity-80" strokeWidth={2.5} />
						改用这段文案重新发送
					</button>
				</div>
			) : null}

			{isDone ? (
				<div className="flex items-center justify-between gap-2 px-4 pb-4">
					<button
						type="button"
						onClick={() => {
							setUndoing(true);
							void undoLast(sessionId).finally(() => setUndoing(false));
						}}
						disabled={undoing}
						className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40"
					>
						{undoing ? '撤销中…' : '撤销回溯'}
					</button>
					<button
						type="button"
						onClick={() => close(sessionId)}
						className="rounded-lg bg-accent px-3 py-1.5 font-sans text-[12px] font-semibold text-on-accent transition-colors hover:bg-accent-hover"
					>
						完成
					</button>
				</div>
			) : null}

			{state.phase === 'error' ? (
				<div className="flex flex-wrap items-center justify-end gap-2 px-4 pb-4">
					<p
						className="mr-auto min-w-0 flex-1 text-[11px] leading-snug text-warn"
						title={state.error ?? ''}
					>
						{state.error || '回溯失败'}
					</p>
					{state.rewindId && !state.resendPending ? (
						<button
							type="button"
							onClick={() => void undoLast(sessionId).finally(() => close(sessionId))}
							className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-ink transition-colors hover:bg-ink/[0.06]"
						>
							撤销回溯
						</button>
					) : null}
					{state.recovery ? (
						<>
							<button
								type="button"
								onClick={() => void recover(sessionId, 'abandon').finally(() => close(sessionId))}
								className="rounded-lg px-3 py-1.5 font-sans text-[12px] text-mute transition-colors hover:bg-ink/[0.06] hover:text-ink"
							>
								放弃恢复
							</button>
							<button
								type="button"
								onClick={() => void recover(sessionId, 'retry')}
								className="rounded-lg px-3 py-1.5 font-sans text-[12px] font-semibold text-ink transition-colors hover:bg-ink/[0.06]"
							>
								从检查点重试
							</button>
						</>
					) : state.resendPending ? (
						<button
							type="button"
							onClick={() => void retryResend(sessionId)}
							className="rounded-lg px-3 py-1.5 font-sans text-[12px] font-semibold text-ink transition-colors hover:bg-ink/[0.06]"
						>
							重试发送
						</button>
					) : state.action ? (
						<button
							type="button"
							onClick={() => void retry(sessionId)}
							className="rounded-lg px-3 py-1.5 font-sans text-[12px] font-semibold text-ink transition-colors hover:bg-ink/[0.06]"
						>
							重试
						</button>
					) : null}
					<button
						type="button"
						onClick={() => {
							if (!state.settled && !state.resendPending) {
								abandon(sessionId);
							} else {
								close(sessionId);
							}
						}}
						className="rounded-lg bg-accent px-3 py-1.5 font-sans text-[12px] font-semibold text-on-accent transition-colors hover:bg-accent-hover"
					>
						{state.settled || state.resendPending ? '关闭' : '放弃'}
					</button>
				</div>
			) : null}

			{restoreDisabled && state.phase === 'dialog' ? (
				<p className="px-4 pb-3 text-[10px] leading-snug text-mute">
					此条没有文件检查点：仅可截断对话并重发文案，工作区文件不会回滚。
				</p>
			) : null}
		</dialog>
	);
}


/** 切点 pill（哑组件）：展示截断摘要，按钮打开锚定该切点的弹窗。 */
export function RewindCutPill({
	digest,
	removedRows,
	onClick,
}: {
	digest: string;
	removedRows: number;
	onClick: () => void;
}) {
	const label = digest
		? `「${digest}」 已截断 ${removedRows} 条`
		: `已截断 ${removedRows} 条`;
	return (
		<button
			type="button"
			onClick={onClick}
			className="mx-auto my-1 flex max-w-[85%] items-center gap-2 rounded-full border border-line/50 bg-paper-deep/60 px-3 py-1 text-[11px] text-mute transition-colors hover:border-line hover:text-ink"
			title="查看这次回溯"
		>
			<span className="truncate">{label}</span>
			<RotateCcw className="h-3 w-3 shrink-0" strokeWidth={2} />
		</button>
	);
}
