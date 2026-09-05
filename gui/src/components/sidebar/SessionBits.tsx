import {
	Archive,
	Clipboard,
	GitBranch,
	MoreHorizontal,
	Pencil,
	RotateCcw,
	Trash2,
} from 'lucide-react';
import type {ReactNode} from 'react';
import type {ContextMenuItem} from '@/components/ui/ContextMenu';
import {confirmDialog, promptDialog} from '@/lib/inlineDialog';
import {formatRelativeShort} from '@/lib/time';
import {cn} from '@/lib/utils';

/**
 * 侧栏会话列表公共件（2026-09-05 复用审计 ⑤）：
 * SpaceFolder（工作区）与 SideChatSection（Chat）曾各自平行实现
 * 行渲染 / 三点菜单 / 收合树，逐行几乎相同。收敛于此，差异 props 化。
 */

/** 会话行（li + 主按钮 + 悬浮「···」菜单按钮）。两套列表唯一的行实现。 */
export function SessionRow({
	session,
	active,
	running,
	doneUnseen = false,
	peerLabel = '',
	onSelect,
	onMenu,
	affordanceTitle,
}: {
	session: {id: string; title: string; updatedAt: number; archived?: boolean};
	active: boolean;
	running: boolean;
	/** 任务完成且未回看 → 静态绿色微光。 */
	doneUnseen?: boolean;
	/** 同工作区 peer 在场摘要（仅工作区列表使用）。 */
	peerLabel?: string;
	onSelect: () => void;
	onMenu: (e: React.MouseEvent) => void;
	affordanceTitle: string;
}) {
	return (
		<li
			className='group/item relative'
			style={{
				contentVisibility: 'auto',
				containIntrinsicSize: 'auto 32px',
			}}
		>
			<button
				type='button'
				onClick={onSelect}
				onContextMenu={onMenu}
				title={peerLabel ? `也在改 ${peerLabel}` : undefined}
				className={cn(
					'xy-pressable flex w-full items-center gap-2 rounded-md py-1 pr-2 pl-4 text-left text-[13px]',
					active
						? 'bg-glass-strong font-medium text-accent'
						: session.archived
							? 'text-ink-soft/80 hover:bg-glass-hover'
							: 'text-ink-soft hover:bg-glass-hover',
				)}
			>
				<span
					className={cn(
						'xy-run-dot',
						running ? 'is-running' : doneUnseen && 'is-done-unseen',
					)}
					aria-hidden='true'
				/>
				<span
					className={cn(
						'min-w-0 flex-1 truncate',
						session.archived && 'text-mute',
					)}
				>
					{session.title}
				</span>
				{peerLabel && !session.archived ? (
					<span className='max-w-[5.5rem] shrink-0 truncate font-mono text-[10px] text-warn/90 group-hover/item:opacity-0'>
						{peerLabel}
					</span>
				) : (
					<span className='xy-session-meta shrink-0 font-mono text-[10px] text-mute/70 group-hover/item:opacity-0'>
						{formatRelativeShort(session.updatedAt)}
					</span>
				)}
			</button>
			<button
				type='button'
				aria-label={session.archived ? '已归档对话操作' : '对话操作'}
				title={affordanceTitle}
				onClick={onMenu}
				className='xy-icon-btn xy-sidebar-affordance absolute top-1/2 right-1 -translate-y-1/2 translate-x-1 rounded p-1 text-mute opacity-0 invisible pointer-events-none hover:bg-glass-hover hover:text-ink group-hover/item:visible group-hover/item:pointer-events-auto group-hover/item:opacity-100 group-hover/item:translate-x-0'
			>
				<MoreHorizontal className='h-3.5 w-3.5' />
			</button>
		</li>
	);
}

/** xy-sidebar-tree 收合树（div+ul），两套列表共用。 */
export function SessionTree({
	open,
	children,
}: {
	open: boolean;
	children: ReactNode;
}) {
	return (
		<div
			className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')}
			aria-hidden={!open}
		>
			<ul className='min-h-0 overflow-hidden pb-1'>{children}</ul>
		</div>
	);
}

export type SessionMenuHandlers = {
	/** 复制会话 ID（Chat 分区提供；工作区菜单不提供）。 */
	onCopyId?: () => void;
	/** 重命名；回调收到用户输入的新标题。 */
	onRename?: (title: string) => void;
	/** 分叉：空会话置灰（transcript 为空时后端 /fork 必 404）。 */
	onFork?: {run: () => void; disabled?: boolean};
	onArchive?: () => void;
	onRestore?: () => void;
	/** 已归档菜单的删除（危险确认内置于本工厂）。 */
	onDelete?: () => void;
};

/**
 * 会话三点菜单项工厂：工作区与 Chat 分区共用一套菜单语义
 * （归档门槛：常态菜单不提供删除；删除仅出现在已归档菜单且带危险确认）。
 */
export function buildSessionMenuItems(
	session: {id: string; title: string; archived?: boolean},
	handlers: SessionMenuHandlers,
): ContextMenuItem[] {
	const items: ContextMenuItem[] = [];
	if (handlers.onCopyId) {
		items.push({
			kind: 'action',
			id: 'copy-id',
			label: '复制对话 ID',
			icon: <Clipboard className='h-3.5 w-3.5' strokeWidth={1.9} />,
			onSelect: handlers.onCopyId,
		});
	}
	if (Boolean(session.archived)) {
		if (handlers.onRestore) {
			items.push({
				kind: 'action',
				id: 'restore',
				label: '恢复对话',
				icon: <RotateCcw className='h-3.5 w-3.5' strokeWidth={1.9} />,
				onSelect: handlers.onRestore,
			});
		}
		if (handlers.onDelete) {
			items.push({kind: 'sep'});
			items.push({
				kind: 'action',
				id: 'delete',
				label: '删除对话',
				danger: true,
				icon: <Trash2 className='h-3.5 w-3.5' strokeWidth={1.9} />,
				onSelect: () => {
					void (async () => {
						const ok = await confirmDialog({
							title: '删除已归档对话？',
							body: `「${session.title}」将连同全部聊天记录永久删除，不可恢复。`,
							confirmText: '删除',
							danger: true,
						});
						if (ok) {
							handlers.onDelete?.();
						}
					})();
				},
			});
		}
	} else {
		if (handlers.onRename) {
			items.push({
				kind: 'action',
				id: 'rename',
				label: '重命名对话',
				icon: <Pencil className='h-3.5 w-3.5' strokeWidth={1.9} />,
				onSelect: () => {
					void (async () => {
						const next = await promptDialog({
							title: '重命名对话',
							initial: session.title,
							confirmText: '保存',
						});
						if (next != null) {
							handlers.onRename?.(next);
						}
					})();
				},
			});
		}
		if (handlers.onFork) {
			items.push({
				kind: 'action',
				id: 'fork',
				label: '分叉对话',
				disabled: handlers.onFork.disabled,
				icon: <GitBranch className='h-3.5 w-3.5' strokeWidth={1.9} />,
				onSelect: handlers.onFork.run,
			});
		}
		if (handlers.onArchive) {
			items.push({
				kind: 'action',
				id: 'archive',
				label: '归档对话',
				icon: <Archive className='h-3.5 w-3.5' strokeWidth={1.9} />,
				onSelect: handlers.onArchive,
			});
		}
	}
	return items;
}
