import {
	Check,
	ChevronRight,
	ListTodo,
	MessageCircle,
	Network,
	Paperclip,
	Server,
} from 'lucide-react';
import {useEffect, useRef, useState} from 'react';

import {cn} from '@/lib/utils';
import {MenuSeparator} from '@/components/ui/MenuSeparator';
import type {AgentMode} from '@/lib/agentMode';

/**
 * Composer 左侧 + 按钮的 Cursor 风格快捷菜单（对齐参考图一）。
 *
 * - 顶部：Cursor 式**纯文本搜索**——只有文字与光标，无搜索框底/边框。
 * - 模式区：Plan / Ask / Multi-Agent（Plan、Ask 切 agentMode；Multi-Agent 是开关）。
 * - 底部：Files（添加文件）/ MCP（执行 /mcp）。
 * - 不含技能栏、无快捷键胶囊。
 *
 * 视觉沿用 XEYO 令牌（玻璃底 xy-menu-flyout + --xy-* 语义色 + ease-out-soft）。
 */

type ModeEntry = {
	key: string;
	label: string;
	description: string;
	Icon: typeof ListTodo;
};

const MODES: ModeEntry[] = [
	{
		key: 'plan',
		label: 'Plan',
		description: 'Generate an implementation plan',
		Icon: ListTodo,
	},
	{
		key: 'ask',
		label: 'Ask',
		description: 'Answer questions without making edits',
		Icon: MessageCircle,
	},
	{
		key: 'multi-agent',
		label: 'Multi-Agent',
		description: 'Orchestrate multiple subagents in parallel',
		Icon: Network,
	},
];

type Props = {
	open: boolean;
	menuId?: string;
	agentMode: AgentMode;
	multiAgent: boolean;
	uploading: boolean;
	onSelectMode: (mode: AgentMode) => void;
	onToggleMultiAgent: () => void;
	onAddFile: () => void;
	onRunMcp: () => void;
};

export function ComposerQuickMenu({
	open,
	menuId,
	agentMode,
	multiAgent,
	uploading,
	onSelectMode,
	onToggleMultiAgent,
	onAddFile,
	onRunMcp,
}: Props) {
	const [query, setQuery] = useState('');
	const searchRef = useRef<HTMLInputElement>(null);

	useEffect(() => {
		if (open) {
			setQuery('');
			requestAnimationFrame(() => searchRef.current?.focus());
		}
	}, [open]);

	const q = query.trim().toLowerCase();
	const filtered = !q
		? MODES
		: MODES.filter(
				m =>
					m.label.toLowerCase().includes(q) ||
					m.description.toLowerCase().includes(q),
			);

	return (
		<div
			id={menuId}
			role="menu"
			className="xy-menu-flyout absolute bottom-full left-0 z-50 mb-1.5 flex max-h-[min(420px,60vh)] w-[300px] flex-col overflow-hidden rounded-2xl border border-line/50 p-1.5"
		>
			{/* Cursor 式纯文本搜索：无框底，仅文字 + 光标 */}
			<div className="px-2.5 pb-1 pt-1.5">
				<input
					ref={searchRef}
					value={query}
					onChange={e => setQuery(e.target.value)}
					placeholder="Search modes, actions…"
					className="w-full bg-transparent font-sans text-[12.5px] text-ink outline-none placeholder:text-mute"
				/>
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto">
				{filtered.length === 0 ? (
					<p className="px-2.5 py-2 text-[11.5px] text-mute">无匹配项。</p>
				) : (
					<div className="flex flex-col gap-0.5">
						{filtered.map(m => {
							const Icon = m.Icon;
							const isMulti = m.key === 'multi-agent';
							const active = isMulti
								? multiAgent
								: agentMode === (m.key as AgentMode);
							return (
								<button
									key={m.key}
									type="button"
									role="menuitemradio"
									aria-checked={active}
									onClick={() => {
										if (isMulti) {
											onToggleMultiAgent();
										} else {
											onSelectMode(m.key as AgentMode);
										}
									}}
									className={cn(
										'xy-menu-row flex w-full items-center gap-2 px-2 py-1.5 text-left',
										active && 'is-active',
									)}
								>
									<Icon
										className={cn(
											'h-4 w-4 shrink-0',
											isMulti ? 'text-mute' : 'text-mute',
										)}
										strokeWidth={1.9}
									/>
									<span className="min-w-0 flex-1 truncate">
										<span className="text-[13px] font-medium text-ink">
											{m.label}
										</span>
										<span className="ml-2 text-[11px] text-mute">
											{m.description}
										</span>
									</span>
									{active ? (
										<Check
											className="h-3.5 w-3.5 shrink-0 text-accent"
											strokeWidth={2.4}
										/>
									) : null}
								</button>
							);
						})}
					</div>
				)}
			</div>

			<MenuSeparator />
			<div className="flex flex-col gap-0.5">
				<button
					type="button"
					role="menuitem"
					disabled={uploading}
					onClick={onAddFile}
					className="xy-menu-row flex w-full items-center gap-2 px-2 py-1.5 text-left text-[13px] text-ink-soft disabled:cursor-default disabled:text-mute/55"
				>
					<Paperclip className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.9} />
					<span>Files</span>
				</button>
				<button
					type="button"
					role="menuitem"
					onClick={onRunMcp}
					className="xy-menu-row flex w-full items-center gap-2 px-2 py-1.5 text-left text-[13px] text-ink-soft"
				>
					<Server className="h-4 w-4 shrink-0 text-mute" strokeWidth={1.9} />
					<span className="min-w-0 flex-1">MCP</span>
					{/* 参考图：行尾 chevron 指示进入面板 */}
					<ChevronRight
						className="h-3.5 w-3.5 shrink-0 text-mute"
						strokeWidth={1.75}
					/>
				</button>
			</div>
		</div>
	);
}
