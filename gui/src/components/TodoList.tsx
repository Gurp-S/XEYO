import {
	CheckCircle2,
	ChevronDown,
	Circle,
	ListX,
	Loader2,
} from 'lucide-react';
import {memo, useEffect, useMemo, useState} from 'react';
import type {TodoItemView, TodoSnapshot} from '@/lib/toolActivity';
import {cn} from '@/lib/utils';
import {PanelCollapse} from './PanelCollapse';

type Props = {
	snapshot: TodoSnapshot;
	/** 输入框上方 dock：更紧凑 chrome，tool 运行时展开。 */
	dock?: boolean;
	/** 手动结束生命周期 — 从 UI 关闭当前列表。 */
	onDismiss?: () => void;
};

function todoLabel(item: TodoItemView): string {
	if (item.status === 'in_progress') {
		return item.activeForm || item.content;
	}
	return item.content;
}

function StatusIcon({
	status,
	running,
}: {
	status: TodoItemView['status'];
	running?: boolean;
}) {
	if (status === 'completed') {
		return (
			<CheckCircle2
				className="size-3.5 shrink-0 text-ok"
				strokeWidth={2}
				aria-hidden
			/>
		);
	}
	if (status === 'in_progress') {
		return (
			<Loader2
				className={cn(
					'xy-todo-spin size-3.5 shrink-0 text-accent',
					running !== false && 'animate-spin',
				)}
				strokeWidth={2}
				aria-hidden
			/>
		);
	}
	return (
		<Circle
			className="size-3.5 shrink-0 text-mute/55"
			strokeWidth={2}
			aria-hidden
		/>
	);
}

/**
 * Copilot Chat 风格 todo 清单。
 * 完成后项保留行（带勾选）；全部完成或用户关闭时隐藏整个面板。
 */
function TodoListInner({snapshot, dock = false, onDismiss}: Props) {
	const {todos, running} = snapshot;
	const stats = useMemo(() => {
		let done = 0;
		let active: TodoItemView | undefined;
		for (const t of todos) {
			if (t.status === 'completed') {
				done += 1;
			} else if (t.status === 'in_progress' && !active) {
				active = t;
			}
		}
		return {done, total: todos.length, active};
	}, [todos]);
	/** TodoWrite 工具本身可能一帧就结束；有 in_progress 项时仍算进行中。 */
	const live = running || Boolean(stats.active);
	const [expanded, setExpanded] = useState(Boolean(dock) || live);

	useEffect(() => {
		if (live) {
			setExpanded(true);
		}
	}, [live, snapshot.id]);

	if (todos.length === 0) {
		return null;
	}

	const subtitle = stats.active
		? todoLabel(stats.active)
		: live
			? 'Updating…'
			: `${stats.done}/${stats.total} done`;

	return (
		<div
			className={cn(
				'xy-panel-ask',
				expanded && 'is-expanded',
				!dock && 'xy-panel-ask-card mt-2.5',
			)}
			role="region"
			aria-label={`Todo list, ${stats.done} of ${stats.total} completed`}
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
				<div className="min-w-0 flex-1">
					<div className="flex items-center gap-2">
						<span className="xy-panel-ask-title">Todo</span>
						<span className="xy-panel-ask-count">
							({stats.done}/{stats.total})
						</span>
					</div>
					{!expanded ? (
						<p className="xy-panel-ask-sub">{subtitle}</p>
					) : null}
				</div>
				{onDismiss || live ? (
					<div className="ml-auto flex shrink-0 items-center gap-1">
						{onDismiss ? (
							<button
								type="button"
								className="xy-panel-ask-dismiss"
								aria-label="删除当前 Todo 列表"
								onClick={e => {
									e.stopPropagation();
									onDismiss();
								}}
							>
								<ListX className="size-3.5" strokeWidth={1.75} />
							</button>
						) : null}
						{live ? (
							<span
								className="xy-panel-ask-dot !ml-0"
								aria-hidden="true"
							/>
						) : null}
					</div>
				) : null}
			</div>
			<PanelCollapse open={expanded} className="xy-panel-ask-body xy-panel-ask-todos">
					<ul>
						{todos.map((item, i) => {
							const label = todoLabel(item);
							const isDone = item.status === 'completed';
							const isActive = item.status === 'in_progress';
							return (
								<li
									key={`${i}-${item.content}`}
									className="xy-panel-ask-todo-item"
								>
									<span className="mt-0.5">
										<StatusIcon
											status={item.status}
											running={isActive}
										/>
									</span>
									<span
										className={cn(
											'min-w-0 flex-1 font-sans text-[12px] leading-snug',
											isDone &&
												'text-mute line-through decoration-mute/60',
											isActive && 'text-ink',
											!isDone && !isActive && 'text-ink-soft',
										)}
									>
										{label}
									</span>
								</li>
							);
						})}
					</ul>
			</PanelCollapse>
		</div>
	);
}

export const TodoList = memo(TodoListInner);
