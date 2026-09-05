import {DiffPreview} from '@/components/DiffPreview';
import {
	type RollbackTreeNode,
} from '@/lib/rollbackDiffTree';
import {cn} from '@/lib/utils';
import {ChevronRight, FileText, Folder, Trash2} from 'lucide-react';
import {type ReactNode, useMemo, useState} from 'react';

function TreeSection({open, children}: {open: boolean; children: ReactNode}) {
	return (
		<div
			className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')}
			aria-hidden={!open}
		>
			<div className="min-h-0 overflow-hidden">{children}</div>
		</div>
	);
}

function TreeRow({
	depth,
	open,
	chev,
	active,
	onClick,
	children,
}: {
	depth: number;
	open?: boolean;
	chev?: boolean;
	active?: boolean;
	onClick?: () => void;
	children: ReactNode;
}) {
	return (
		<button
			type="button"
			onClick={onClick}
			className={cn(
				'flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left transition-colors',
				active
					? 'bg-glass-strong text-ink'
					: 'text-ink-soft hover:bg-glass-hover hover:text-ink',
			)}
			style={{paddingLeft: 8 + depth * 12}}
		>
			<span className="flex w-3 shrink-0 items-center justify-center text-mute">
				{chev ? (
					<ChevronRight
						className={cn(
							'h-3 w-3 transition-transform duration-150',
							open && 'rotate-90',
						)}
						strokeWidth={2}
					/>
				) : (
					<span className="w-3" />
				)}
			</span>
			{children}
		</button>
	);
}

function DiffStats({add, del}: {add: number; del: number}) {
	if (add <= 0 && del <= 0) {
		return null;
	}
	return (
		<span className="ml-auto shrink-0 font-mono text-[10px] tabular-nums">
			{add > 0 ? <span className="text-ok">+{add}</span> : null}
			{del > 0 ? (
				<span className={add > 0 ? 'ml-1 text-danger' : 'text-danger'}>
					-{del}
				</span>
			) : null}
		</span>
	);
}

function TreeNodeView({
	node,
	depth,
	openMap,
	onToggle,
}: {
	node: RollbackTreeNode;
	depth: number;
	openMap: Record<string, boolean>;
	onToggle: (key: string) => void;
}) {
	if (node.type === 'dir') {
		const open = openMap[node.key] ?? true;
		return (
			<div>
				<TreeRow
					depth={depth}
					chev
					open={open}
					onClick={() => onToggle(node.key)}
				>
					<Folder className="h-3 w-3 shrink-0 text-mute" strokeWidth={2} />
					<span className="min-w-0 truncate font-mono text-[11px]">{node.name}</span>
				</TreeRow>
				<TreeSection open={open}>
					<div className="pb-0.5">
						{node.children.map(child => (
							<TreeNodeView
								key={child.key}
								node={child}
								depth={depth + 1}
								openMap={openMap}
								onToggle={onToggle}
							/>
						))}
					</div>
				</TreeSection>
			</div>
		);
	}

	const open = openMap[node.key] ?? false;
	const {entry} = node;
	const Icon = entry.kind === 'trash' ? Trash2 : FileText;

	return (
		<div>
			<TreeRow
				depth={depth}
				chev
				open={open}
				active={open}
				onClick={() => onToggle(node.key)}
			>
				<Icon
					className={cn(
						'h-3 w-3 shrink-0',
						entry.kind === 'trash' ? 'text-warn' : 'text-mute',
					)}
					strokeWidth={2}
				/>
				<span className="min-w-0 truncate font-mono text-[11px]">{node.name}</span>
				<DiffStats add={entry.stats.add} del={entry.stats.del} />
			</TreeRow>
			<TreeSection open={open}>
				<div
					className="pb-1.5"
					style={{paddingLeft: 8 + (depth + 1) * 12 + 15}}
				>
					{entry.diff ? (
						<DiffPreview diff={entry.diff} className="text-[10px]" />
					) : (
						<p className="rounded-md bg-paper-deep/70 px-2 py-1.5 font-mono text-[10px] text-mute ring-1 ring-line/30">
							{entry.kind === 'trash' ? '回滚后将删除此文件' : '无法生成 diff 预览'}
						</p>
					)}
				</div>
			</TreeSection>
		</div>
	);
}

export function RollbackDiffTree({nodes}: {nodes: RollbackTreeNode[]}) {
	const defaultOpen = useMemo(() => {
		const map: Record<string, boolean> = {};
		const walk = (list: RollbackTreeNode[]) => {
			for (const node of list) {
				map[node.key] = node.type === 'dir';
				if (node.type === 'dir') {
					walk(node.children);
				}
			}
		};
		walk(nodes);
		return map;
	}, [nodes]);

	const [openMap, setOpenMap] = useState(defaultOpen);

	const toggle = (key: string) => {
		setOpenMap(prev => ({...prev, [key]: !prev[key]}));
	};

	if (nodes.length === 0) {
		return (
			<p className="px-1 py-2 font-mono text-[10px] text-mute">
				此回溯不会改动工作区文件，仅截断对话记录。
			</p>
		);
	}

	return (
		<div className="xy-rewind-diff-tree rounded-lg bg-paper-deep/40 p-1.5 ring-1 ring-line/35">
			{nodes.map(node => (
				<TreeNodeView
					key={node.key}
					node={node}
					depth={0}
					openMap={openMap}
					onToggle={toggle}
				/>
			))}
		</div>
	);
}
