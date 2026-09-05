import {
	ArrowUpRight,
	ChevronRight,
	Loader2,
	Search,
	ShieldCheck,
	X,
} from 'lucide-react';
import {useEffect, useMemo, useState} from 'react';

import {
	fetchMcpStatus,
	mcpOp,
	type McpServerView,
	type McpStatusReport,
} from '@/lib/api/mcp';
import {openPageView} from '@/lib/appNav';
import {cn} from '@/lib/utils';

const STATUS_LABEL: Record<string, {label: string; cls: string}> = {
	ready: {label: '就绪', cls: 'text-ok'},
	failed: {label: '失败', cls: 'text-danger'},
	unapproved: {label: '待批准', cls: 'text-warn'},
	denied: {label: '企业拒绝', cls: 'text-danger'},
	declared: {label: '未启动', cls: 'text-mute'},
	starting: {label: '启动中', cls: 'text-mute'},
};

function ServerCard({
	server,
	onChanged,
	busy,
	setBusy,
}: {
	server: McpServerView;
	onChanged: () => void;
	busy: string | null;
	setBusy: (key: string | null) => void;
}) {
	const [open, setOpen] = useState(false);
	const status = STATUS_LABEL[server.status] ?? STATUS_LABEL.declared!;
	const effectiveEnabled =
		server.enabled_tools == null
			? server.raw_tools
			: server.enabled_tools;

	const run = async (key: string, fn: () => Promise<unknown>) => {
		setBusy(key);
		try {
			await fn();
			onChanged();
		} finally {
			setBusy(null);
		}
	};

	return (
		<div className="rounded-lg border border-line/50 bg-glass-strong">
			<div className="flex items-center gap-1.5 px-2 py-1.5">
				<button
					type="button"
					aria-expanded={open}
					onClick={() => setOpen(v => !v)}
					disabled={server.raw_tools.length === 0}
					className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
				>
					<ChevronRight
						className={cn(
							'h-3.5 w-3.5 shrink-0 text-mute transition-transform duration-150',
							open && 'rotate-90',
						)}
						strokeWidth={1.8}
					/>
					<span className="truncate font-mono text-[12px] text-ink">
						{server.id}
					</span>
					<span className={cn('shrink-0 text-[10px]', status.cls)}>
						{status.label}
					</span>
				</button>
				{server.scope ? (
					<span className="shrink-0 rounded bg-paper-deep px-1 py-0.5 text-[9px] text-mute">
						{server.scope}
					</span>
				) : null}
				{server.status !== 'unapproved' ? (
					<button
						type="button"
						role="switch"
						aria-checked={server.enabled}
						aria-label={`启用 ${server.id}`}
						disabled={busy !== null || server.denied}
						onClick={() =>
							void run(`toggle:${server.id}`, () =>
								mcpOp(server.id, server.enabled ? 'disable' : 'enable'),
							)
						}
						className={cn(
							'xy-press relative h-4 w-7 shrink-0 rounded-full transition-colors',
							server.enabled
								? 'bg-accent'
								: 'bg-paper-deep ring-1 ring-line',
							(busy !== null || server.denied) && 'opacity-40',
						)}
					>
						<span
							className={cn(
								'absolute top-0.5 h-3 w-3 rounded-full bg-paper transition-transform',
								server.enabled ? 'translate-x-3.5' : 'translate-x-0.5',
							)}
						/>
					</button>
				) : null}
				{server.status === 'unapproved' ? (
					<button
						type="button"
						disabled={busy !== null}
						onClick={() =>
							void run(`approve:${server.id}`, () =>
								mcpOp(server.id, 'approve'),
							)
						}
						className="xy-press inline-flex h-5 shrink-0 items-center gap-1 rounded-full bg-accent/10 px-1.5 text-[10px] text-accent hover:bg-accent/20 disabled:opacity-40"
					>
						<ShieldCheck className="h-3 w-3" strokeWidth={2} />
						批准
					</button>
				) : null}
			</div>
			{open && server.raw_tools.length > 0 ? (
				<div className="border-t border-line/40 px-2 pb-2 pt-1">
					{server.raw_tools.map(name => {
						const checked = effectiveEnabled.includes(name);
						const hidden = server.tools.find(t => t.name === name)?.hidden;
						return (
							<label
								key={name}
								className="flex cursor-pointer items-center gap-2 px-1 py-1 text-[12px] text-ink-soft hover:bg-paper-deep/50"
							>
								<input
									type="checkbox"
									checked={checked}
									disabled={busy !== null || server.denied}
									onChange={() =>
										void run(`tool:${server.id}:${name}`, () =>
											mcpOp(server.id, 'tool', {
												raw_tool: name,
												enabled: !checked,
											}),
										)
									}
									className="accent-accent"
								/>
								<span className="min-w-0 flex-1 truncate font-mono">
									{name}
								</span>
								{hidden ? (
									<span className="shrink-0 rounded bg-paper-deep px-1 text-[9px] text-mute">
										隐藏
									</span>
								) : null}
							</label>
						);
					})}
				</div>
			) : null}
		</div>
	);
}

/**
 * MCP 面板（smoke-test #8；视觉参照 + 菜单参考图：Search / Manage / 空态）。
 * 从加号菜单打开：搜索服务器与工具、逐工具勾选、启用/停用、批准（project 信任）。
 * Manage 按钮跳转到页面级「扩展中心」视图（不再有内联 manage 分支）。
 */
export function McpPanel({open, onClose}: {open: boolean; onClose: () => void}) {
	const [report, setReport] = useState<McpStatusReport | null>(null);
	const [query, setQuery] = useState('');
	const [busy, setBusy] = useState<string | null>(null);
	const [tick, setTick] = useState(0);

	useEffect(() => {
		if (!open) {
			setQuery('');
			setReport(null);
			return;
		}
		let alive = true;
		setBusy(null);
		void fetchMcpStatus().then(r => {
			if (alive) {
				setReport(r);
			}
		});
		return () => {
			alive = false;
		};
	}, [open, tick]);

	const servers = useMemo(() => {
		const list = report?.servers ?? [];
		const q = query.trim().toLowerCase();
		if (!q) {
			return list;
		}
		return list.filter(
			s =>
				s.id.toLowerCase().includes(q) ||
				s.raw_tools.some(t => t.toLowerCase().includes(q)),
		);
	}, [report, query]);

	const refresh = () => setTick(t => t + 1);

	if (!open) {
		return null;
	}

	return (
		<div className="xy-menu-flyout absolute bottom-full left-0 z-[1000] mb-1.5 flex max-h-[min(60vh,540px)] w-[min(360px,calc(100vw-1rem))] flex-col overflow-hidden rounded-xl">
			<div className="flex items-center gap-1.5 border-b border-line/40 p-1.5">
				<button
					type="button"
					aria-label="关闭 MCP 面板"
					title="关闭"
					onClick={onClose}
					className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-paper-deep hover:text-ink"
				>
					<X className="h-3.5 w-3.5" />
				</button>
				<div className="relative min-w-0 flex-1">
					<Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-mute" />
					<input
						value={query}
						onChange={e => setQuery(e.target.value)}
						placeholder="Search MCPs…"
						aria-label="搜索 MCP"
						className="h-7 w-full rounded-lg bg-paper-deep pl-7 pr-2 text-[12.5px] text-ink outline-none placeholder:text-mute"
					/>
				</div>
				<button
					type="button"
					title="在扩展中心管理插件 / MCP / 技能"
					onClick={() => {
						onClose();
						openPageView('plugins');
					}}
					className="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg px-2 text-[11px] text-mute transition-colors hover:bg-paper-deep hover:text-ink"
				>
					Manage
					<ArrowUpRight className="h-3 w-3" strokeWidth={1.75} />
				</button>
			</div>

			{report && !report.ok ? (
				<div className="px-3 py-4 text-[12px] leading-relaxed text-danger">
					加载失败：{report.message}
				</div>
			) : null}

			{report && report.ok ? (
				<div className="xy-hover-scroll min-h-0 flex-1 overflow-y-auto p-1.5">
					{servers.length === 0 ? (
						<div className="px-3 py-6 text-center text-[12px] text-mute">
							No MCPs Found
							<div className="mt-1 text-[10px] text-mute/80">
								在 {report.workspace || '工作区'}/.xeyo/mcp.json 声明服务器,
								或通过插件安装后重启后端。
							</div>
						</div>
					) : (
						<div className="space-y-1.5 p-1">
							{servers.map(s => (
								<ServerCard
									key={s.id}
									server={s}
									onChanged={refresh}
									busy={busy}
									setBusy={setBusy}
								/>
							))}
						</div>
					)}
				</div>
			) : null}

			{!report ? (
				<div className="flex items-center justify-center gap-2 px-3 py-6 text-[12px] text-mute">
					<Loader2 className="h-4 w-4 animate-spin" />
					加载中…
				</div>
			) : null}
		</div>
	);
}

/** 面板空态/状态引用保持。 */
