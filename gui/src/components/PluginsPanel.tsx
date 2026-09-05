import {
	AlertTriangle,
	Blocks,
	CheckCircle2,
	ChevronDown,
	Circle,
	Loader2,
	PackageOpen,
	Plus,
	RefreshCw,
	Search,
	Server,
	ShieldCheck,
	Sparkles,
	Wand2,
	X,
	XCircle,
} from 'lucide-react';
import {
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type CSSProperties,
	type KeyboardEvent,
} from 'react';

import {
	fetchMcpStatus,
	mcpOp,
	patchExtensions,
	type McpServerView,
	type McpStatusReport,
} from '@/lib/api/mcp';
import {
	fetchExtensionSettings,
	fetchPlugins,
	type ExtensionSettingsView,
	type PluginView,
	type PluginsReport,
} from '@/lib/api/plugins';
import {fetchSkills, type SkillInfo, type SkillsReport} from '@/lib/api/skills';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';

/**
 * 扩展中心（插件 / MCP / Skill 三页）。
 *
 * 入口：左侧侧边栏「插件 / MCP」（ChatPage 覆盖层）。三 tab 共享搜索框，
 * 每类条目带状态指示（启用 / 未启用 / 错误 / 待批准…）与快速启用开关；
 * 顶部为扩展层总开关。数据面：
 * - 插件：GET /v1/plugins（发现 + lockfile 登记 + 坏清单）
 * - MCP：GET /v1/mcp（服务器视图，含逐工具白名单，行内可展开工具清单）
 * - Skill：GET /v1/skills（启用且 user-invocable）+ GET /v1/extensions/settings
 *   （显式停用的技能仍列出，可一键恢复）
 * 启停：POST /v1/extensions/settings（plugins/skills/master）/ /v1/mcp/op（MCP）。
 *
 * 动效与样式见 styles/extensions.css（stagger 入场 / 弹簧开关 / 滑动 tab 指示器，
 * 全部仅 opacity+translate，reduced-motion 降级）。
 */

type TabKey = 'plugins' | 'mcp' | 'skills';

const TABS: {key: TabKey; label: string; icon: typeof Blocks}[] = [
	{key: 'plugins', label: '插件', icon: Blocks},
	{key: 'mcp', label: 'MCP', icon: Server},
	{key: 'skills', label: '技能', icon: Sparkles},
];

const MCP_STATUS: Record<
	string,
	{label: string; icon: typeof Circle; cls: string}
> = {
	ready: {label: '就绪', icon: CheckCircle2, cls: 'text-ok'},
	failed: {label: '失败', icon: XCircle, cls: 'text-danger'},
	unapproved: {label: '待批准', icon: AlertTriangle, cls: 'text-warn'},
	denied: {label: '企业拒绝', icon: XCircle, cls: 'text-danger'},
	declared: {label: '未启动', icon: Circle, cls: 'text-mute'},
	starting: {label: '启动中', icon: Loader2, cls: 'text-mute'},
};

const SOURCE_LABEL: Record<string, string> = {
	workspace: '工作区',
	home: '本机',
	plugin: '插件',
};

type BusyKey = string | null;

/** stagger 入场延迟变量（封顶 12 行，防长列表拖尾）。 */
function staggerVar(i: number): CSSProperties {
	return {'--stagger-i': i} as CSSProperties;
}

function Toggle({
	checked,
	disabled,
	onChange,
	label,
}: {
	checked: boolean;
	disabled: boolean;
	onChange: () => void;
	label: string;
}) {
	return (
		<button
			type="button"
			role="switch"
			aria-checked={checked}
			aria-label={label}
			disabled={disabled}
			data-checked={checked}
			onClick={onChange}
			className={cn(
				'ext-toggle xy-press relative h-5 w-9 shrink-0 rounded-full',
				checked ? 'bg-ok' : 'bg-paper-deep ring-1 ring-line',
				disabled && 'opacity-40',
			)}
		>
			<span
				aria-hidden="true"
				className={cn(
					'ext-toggle-knob absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-paper',
					'shadow-sm',
					checked ? 'translate-x-4' : 'translate-x-0',
				)}
			/>
		</button>
	);
}

function StatusPill({
	icon: Icon,
	label,
	cls,
	spin,
}: {
	icon: typeof Circle;
	label: string;
	cls: string;
	spin?: boolean;
}) {
	return (
		<span
			className={cn(
				'flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-[10.5px]',
				'bg-paper-deep/80',
			)}
		>
			<Icon
				className={cn('h-3 w-3', cls, spin && 'animate-spin')}
				strokeWidth={2}
			/>
			<span className={cls}>{label}</span>
		</span>
	);
}

function EmptyHint({
	icon: Icon,
	title,
	hint,
}: {
	icon: typeof Blocks;
	title: string;
	hint: string;
}) {
	return (
		<div className="flex flex-col items-center gap-1.5 py-8 text-center">
			<Icon className="h-5 w-5 text-mute/60" strokeWidth={1.5} />
			<p className="text-[12.5px] text-mute">{title}</p>
			<p className="text-[10.5px] text-mute/75">{hint}</p>
		</div>
	);
}

function PluginRow({
	plugin,
	index,
	masterOn,
	busy,
	onToggle,
}: {
	plugin: PluginView;
	index: number;
	masterOn: boolean;
	busy: BusyKey;
	onToggle: (name: string, enabled: boolean) => void;
}) {
	const active = masterOn && plugin.enabled;
	const rowBusy = busy === `plugin:${plugin.name}`;
	return (
		<li
			style={staggerVar(index)}
			className={cn(
				'ext-row flex items-center gap-2.5 px-3 py-2.5',
				rowBusy && 'ext-busy',
			)}
		>
			<span
				aria-hidden="true"
				className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-paper-deep ring-1 ring-line/50"
			>
				<Blocks className="h-4 w-4 text-mute" strokeWidth={1.6} />
			</span>
			<div className="min-w-0 flex-1">
				<div className="flex min-w-0 items-center gap-1.5">
					<span className="truncate font-mono text-[12px] text-ink">
						{plugin.name}
					</span>
					{plugin.source_scope ? (
						<span className="shrink-0 rounded bg-paper px-1 py-px text-[9px] text-mute">
							{plugin.source_scope}
						</span>
					) : null}
					{plugin.version ? (
						<span className="shrink-0 font-mono text-[10px] text-mute/70">
							v{plugin.version}
						</span>
					) : null}
				</div>
				{plugin.description ? (
					<p className="mt-0.5 truncate text-[11px] text-mute">
						{plugin.description}
					</p>
				) : null}
				<p className="mt-0.5 flex items-center gap-2 text-[10px] text-mute/70">
					<span>{plugin.skills.length} 技能</span>
					<span>{plugin.mcp_servers.length} MCP</span>
					{plugin.has_hooks ? <span>hooks</span> : null}
				</p>
			</div>
			<StatusPill
				icon={active ? CheckCircle2 : Circle}
				label={active ? '已启用' : '未启用'}
				cls={active ? 'text-ok' : 'text-mute'}
			/>
			<Toggle
				checked={active}
				disabled={!masterOn || busy !== null}
				label={`${plugin.enabled ? '停用' : '启用'}插件 ${plugin.name}`}
				onChange={() => onToggle(plugin.name, !plugin.enabled)}
			/>
		</li>
	);
}


function McpRow({
	server,
	index,
	masterOn,
	busy,
	onToggle,
	onApprove,
	onReload,
}: {
	server: McpServerView;
	index: number;
	masterOn: boolean;
	busy: BusyKey;
	onToggle: (id: string, enabled: boolean) => void;
	onApprove: (id: string) => void;
	onReload: (id: string) => void;
}) {
	const status = MCP_STATUS[server.status] ?? MCP_STATUS.declared!;
	const active = masterOn && server.enabled;
	const pending = server.status === 'unapproved';
	const [expanded, setExpanded] = useState(false);
	const rowBusy =
		busy === `mcp:${server.id}` ||
		busy === `approve:${server.id}` ||
		busy === `reload:${server.id}`;
	const canShowTools = server.tools.length > 0;
	return (
		<li
			style={staggerVar(index)}
			className={cn('ext-row px-3 py-2.5', rowBusy && 'ext-busy')}
		>
			<div className="flex items-center gap-2.5">
				<span
					aria-hidden="true"
					className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-paper-deep ring-1 ring-line/50"
				>
					<Server className="h-4 w-4 text-mute" strokeWidth={1.6} />
				</span>
				{canShowTools ? (
					<button
						type="button"
						aria-expanded={expanded}
						aria-label={`${expanded ? '收起' : '展开'} ${server.id} 工具清单`}
						onClick={() => setExpanded(v => !v)}
						className="ext-focus xy-icon-btn -ml-1 shrink-0 rounded-md p-0.5 text-mute hover:text-ink"
					>
						<ChevronDown
							className={cn(
								'h-3.5 w-3.5 transition-transform duration-200 ease-out',
								expanded && 'rotate-180',
							)}
						/>
					</button>
				) : null}
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 items-center gap-1.5">
						<span className="truncate font-mono text-[12px] text-ink">
							{server.id}
						</span>
						{server.scope ? (
							<span className="shrink-0 rounded bg-paper px-1 py-px text-[9px] text-mute">
								{server.scope}
							</span>
						) : null}
					</div>
					<p className="mt-0.5 flex items-center gap-2 text-[10px] text-mute/70">
						<span>{server.raw_tools.length} 工具</span>
						{server.error ? (
							<span className="truncate text-danger/80">{server.error}</span>
						) : null}
					</p>
				</div>
				<StatusPill
					icon={status.icon}
					label={status.label}
					cls={status.cls}
					spin={server.status === 'starting'}
				/>
				{pending ? (
					<button
						type="button"
						disabled={busy !== null}
						onClick={() => onApprove(server.id)}
						className="ext-focus xy-press inline-flex h-5.5 shrink-0 items-center gap-1 rounded-full bg-accent/10 px-2 text-[10.5px] text-accent hover:bg-accent/20 disabled:opacity-40"
					>
						<ShieldCheck className="h-3 w-3" strokeWidth={2} />
						批准
					</button>
				) : null}
				{!pending && !server.denied ? (
					<Toggle
						checked={active}
						disabled={!masterOn || busy !== null}
						label={`${server.enabled ? '停用' : '启用'}MCP ${server.id}`}
						onChange={() => onToggle(server.id, !server.enabled)}
					/>
				) : null}
				<button
					type="button"
					disabled={busy !== null}
					title="重置该服务（下个会话重建）"
					aria-label={`重置 ${server.id}`}
					onClick={() => onReload(server.id)}
					className="ext-focus xy-icon-btn rounded-md p-1 text-mute hover:bg-paper hover:text-ink disabled:opacity-40"
				>
					<RefreshCw className="h-3 w-3" />
				</button>
			</div>
			{expanded && canShowTools ? (
				<div className="ext-reveal mt-2 space-y-0.5 border-t border-line/50 pt-2">
					<p className="text-[9.5px] text-mute/70">
						{server.enabled_tools === null
							? '白名单：未设置（全量可用）'
							: `白名单：${server.enabled_tools.length} 项`}
					</p>
					{server.tools.map(t => (
						<div
							key={t.name}
							className="flex min-w-0 items-center gap-1.5 rounded px-1 py-0.5 hover:bg-paper"
						>
							<span className="truncate font-mono text-[10.5px] text-ink-soft">
								{t.name}
							</span>
							{t.hidden ? (
								<span className="shrink-0 rounded bg-accent-soft px-1 text-[8.5px] text-mute">
									网关
								</span>
							) : null}
							<span className="ml-auto truncate pl-2 text-[9.5px] text-mute/70">
								{t.description}
							</span>
						</div>
					))}
				</div>
			) : null}
		</li>
	);
}

function SkillRow({
	name,
	info,
	index,
	explicitOff,
	masterOn,
	busy,
	onToggle,
}: {
	name: string;
	/** 来自 /v1/skills 的元数据；停用技能为 undefined。 */
	info: SkillInfo | undefined;
	index: number;
	/** settings.json 显式 enabled:false。 */
	explicitOff: boolean;
	masterOn: boolean;
	busy: BusyKey;
	onToggle: (name: string, enabled: boolean) => void;
}) {
	const enabled = masterOn && !explicitOff;
	const rowBusy = busy === `skill:${name}`;
	return (
		<li
			style={staggerVar(index)}
			className={cn(
				'ext-row flex items-center gap-2.5 px-3 py-2.5',
				rowBusy && 'ext-busy',
			)}
		>
			<span
				aria-hidden="true"
				className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-paper-deep ring-1 ring-line/50"
			>
				<Sparkles className="h-4 w-4 text-mute" strokeWidth={1.6} />
			</span>
			<div className="min-w-0 flex-1">
				<div className="flex min-w-0 items-center gap-1.5">
					<span className="truncate font-mono text-[12px] text-ink">
						{name}
					</span>
					{info ? (
						<span className="shrink-0 rounded bg-paper px-1 py-px text-[9px] text-mute">
							{SOURCE_LABEL[info.source] ?? info.source}
						</span>
					) : (
						<span className="shrink-0 rounded bg-paper px-1 py-px text-[9px] text-mute">
							配置
						</span>
					)}
					{info?.plugin ? (
						<span className="shrink-0 font-mono text-[10px] text-mute/70">
							{info.plugin}
						</span>
					) : null}
				</div>
				{info?.description ? (
					<p className="mt-0.5 truncate text-[11px] text-mute">
						{info.description}
					</p>
				) : (
					<p className="mt-0.5 text-[11px] text-mute/80">
						已在扩展配置中停用；打开开关即恢复。
					</p>
				)}
			</div>
			<StatusPill
				icon={enabled ? CheckCircle2 : Circle}
				label={enabled ? '已启用' : '已停用'}
				cls={enabled ? 'text-ok' : 'text-mute'}
			/>
			<Toggle
				checked={enabled}
				disabled={!masterOn || busy !== null}
				label={`${explicitOff ? '启用' : '停用'}技能 ${name}`}
				onChange={() => onToggle(name, explicitOff)}
			/>
		</li>
	);
}

export function PluginsPanel({active = true}: {active?: boolean}) {
	const [tab, setTab] = useState<TabKey>('plugins');
	const [query, setQuery] = useState('');
	const [busy, setBusy] = useState<BusyKey>(null);
	const [loading, setLoading] = useState(false);
	const [tick, setTick] = useState(0);

	const [plugins, setPlugins] = useState<PluginsReport | null>(null);
	const [mcp, setMcp] = useState<McpStatusReport | null>(null);
	const [skills, setSkills] = useState<SkillsReport | null>(null);
	const [settings, setSettings] = useState<ExtensionSettingsView | null>(null);

	const refresh = useCallback(() => setTick(t => t + 1), []);

	useEffect(() => {
		if (!active) {
			return;
		}
		let alive = true;
		setLoading(true);
		void Promise.all([
			fetchPlugins(),
			fetchMcpStatus(),
			fetchSkills(''),
			fetchExtensionSettings(),
		]).then(([pl, mc, sk, es]) => {
			if (!alive) {
				return;
			}
			setPlugins(pl);
			setMcp(mc);
			setSkills(sk);
			setSettings(es);
			setLoading(false);
		});
		return () => {
			alive = false;
		};
	}, [active, tick]);

	const masterOn =
		(plugins?.enabled_extensions ??
			mcp?.enabled_extensions ??
			settings?.enabled_extensions) === true;
	const run = async (
		key: string,
		fn: () => Promise<{ok: boolean; message?: string}>,
	) => {
		setBusy(key);
		try {
			const r = await fn();
			if (!r.ok) {
				toast.error(r.message || '操作失败');
			}
			refresh();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : String(err));
		} finally {
			setBusy(null);
		}
	};

	const onPluginToggle = (name: string, enabled: boolean) =>
		void run(`plugin:${name}`, () =>
			patchExtensions({plugins: {[name]: {enabled}}}),
		);

	const onMcpToggle = (id: string, enabled: boolean) =>
		void run(`mcp:${id}`, () => mcpOp(id, enabled ? 'enable' : 'disable'));
	const onMcpApprove = (id: string) =>
		void run(`approve:${id}`, () => mcpOp(id, 'approve'));
	const onMcpReload = (id: string) =>
		void run(`reload:${id}`, () => mcpOp(id, 'reload'));
	const onSkillToggle = (name: string, enabled: boolean) =>
		void run(`skill:${name}`, () =>
			patchExtensions({skills: {[name]: {enabled}}}),
		);

	// 扩展层总开关已从 GUI 移除(2026-09-05):enabled_extensions 仅由
	// .xeyo/settings.json 控制,面板只读呈现 masterOn 供行状态判定。

	// ---- 全量(未过滤)集合:tab 徽标计数不随搜索抖动 ----
	const allSkills = useMemo(() => {
		const byName = new Map<string, SkillInfo>();
		for (const s of skills?.skills ?? []) {
			if (s.name) {
				byName.set(s.name, s);
			}
		}
		const extra: {name: string; info?: SkillInfo}[] = [];
		for (const [name, st] of Object.entries(settings?.skills ?? {})) {
			if (!st.enabled && !byName.has(name)) {
				extra.push({name});
			}
		}
		return [
			...Array.from(byName.entries()).map(([n, info]) => ({name: n, info})),
			...extra,
		];
	}, [skills, settings]);

	const q = query.trim().toLowerCase();
	const pluginRows = useMemo(() => {
		const list = plugins?.plugins ?? [];
		if (!q) {
			return list;
		}
		return list.filter(
			p =>
				p.name.toLowerCase().includes(q) ||
				p.description.toLowerCase().includes(q) ||
				p.skills.some(s => s.toLowerCase().includes(q)) ||
				p.mcp_servers.some(s => s.toLowerCase().includes(q)),
		);
	}, [plugins, q]);

	const mcpRows = useMemo(() => {
		const list = mcp?.servers ?? [];
		if (!q) {
			return list;
		}
		return list.filter(
			s =>
				s.id.toLowerCase().includes(q) ||
				s.raw_tools.some(t => t.toLowerCase().includes(q)),
		);
	}, [mcp, q]);

	const explicitSkills = settings?.skills ?? {};
	const skillRows = useMemo(() => {
		if (!q) {
			return allSkills;
		}
		return allSkills.filter(
			x =>
				x.name.toLowerCase().includes(q) ||
				(x.info?.description ?? '').toLowerCase().includes(q),
		);
	}, [allSkills, q]);

	const tabCount: Record<TabKey, number> = {
		plugins: plugins?.plugins.length ?? 0,
		mcp: mcp?.servers.length ?? 0,
		skills: allSkills.length,
	};
	const tabIdx = TABS.findIndex(t => t.key === tab);
	const filteredTotal =
		tab === 'plugins'
			? pluginRows.length
			: tab === 'mcp'
				? mcpRows.length
				: skillRows.length;

	// tab 键盘导航(左右箭头,roving focus)
	const tablistRef = useRef<HTMLDivElement>(null);
	const onTablistKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
		if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') {
			return;
		}
		e.preventDefault();
		const dir = e.key === 'ArrowRight' ? 1 : -1;
		const next = (tabIdx + dir + TABS.length) % TABS.length;
		setTab(TABS[next]!.key);
		const buttons = tablistRef.current?.querySelectorAll<HTMLButtonElement>(
			'[role="tab"]',
		);
		buttons?.[next]?.focus();
	};

	if (!active) {
		return null;
	}

	const pluginErrors = (plugins?.errors ?? []).filter(Boolean);
	const activeTabLabel = TABS[tabIdx]?.label ?? '';

	return (
		<div
			data-testid="extensions-panel"
			className="xy-usage-page flex min-h-0 flex-1 flex-col bg-transparent"
		>
			{/* ---- 工具栏(用量页同构:下边框单行,chips 左 / 搜索+总开关右) ----
			    页面标题由 ChatHeader 随视图切换(「扩展中心」),此处不再重复页头。 */}
			<div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line/40 px-4 py-2">
				<div
					ref={tablistRef}
					role="tablist"
					aria-label="扩展类型"
					onKeyDown={onTablistKeyDown}
					className="flex items-center gap-1.5"
				>
					{TABS.map(t => {
						const Icon = t.icon;
						const sel = tab === t.key;
						return (
							<button
								key={t.key}
								type="button"
								role="tab"
								aria-selected={sel}
								tabIndex={sel ? 0 : -1}
								onClick={() => setTab(t.key)}
								className={cn(
									'ext-focus xy-press inline-flex h-7.5 items-center gap-1.5 rounded-full border px-3 text-[12px] transition-colors duration-200 ease-out',
									sel
										? 'border-transparent bg-accent-soft text-ink shadow-[inset_0_0_0_1px_var(--xy-line)]'
										: 'border-line/70 text-mute hover:border-line hover:bg-paper-deep/50 hover:text-ink-soft',
								)}
							>
								<Icon className="h-3.5 w-3.5" strokeWidth={1.8} />
								{t.label}
								<span
									className={cn(
										'font-mono text-[9.5px] tabular-nums',
										sel ? 'text-mute' : 'text-mute/60',
									)}
								>
									{tabCount[t.key]}
								</span>
							</button>
						);
					})}
				</div>
				<div className="ml-auto flex min-w-0 items-center gap-2">
					<div className="ext-search relative flex h-8 w-56 items-center rounded-full border border-line/60 bg-paper-deep/60 sm:w-72">
						<Search className="pointer-events-none absolute left-3 h-3.5 w-3.5 text-mute" />
						<input
							value={query}
							onChange={e => setQuery(e.target.value)}
							placeholder={`搜索${activeTabLabel}…`}
							aria-label={`搜索${activeTabLabel}`}
							className="ext-focus h-full w-full rounded-full bg-transparent pl-8 pr-14 text-[12.5px] text-ink outline-none placeholder:text-mute"
						/>
						{q ? (
							<span className="absolute right-3 flex items-center gap-1.5">
								<span className="font-mono text-[10px] text-mute">
									{filteredTotal}
								</span>
								<button
									type="button"
									aria-label="清空搜索"
									onClick={() => setQuery('')}
									className="ext-focus xy-icon-btn rounded-full p-0.5 text-mute hover:text-ink"
								>
									<X className="h-3 w-3" />
								</button>
							</span>
						) : null}
					</div>
				</div>
			</div>

			{/* ---- 内容滚动区:列表居中(max-w-3xl),不再贴左留大片空白 ---- */}
			<div className="xy-hover-scroll min-h-0 flex-1 overflow-y-auto px-4 py-4">
				<div className="mx-auto flex w-full max-w-3xl min-w-0 flex-col">
				{loading && !plugins && !mcp && !skills ? (
					<div className="flex items-center justify-center gap-2 py-8 text-[12px] text-mute">
						<Loader2 className="h-4 w-4 animate-spin" />
						加载中…
					</div>
				) : null}

				{tab === 'plugins' ? (
					<div className="space-y-2">
						{plugins && plugins.ok === false ? (
							<p className="rounded-lg bg-danger/5 px-3 py-2 text-[12px] text-danger">
								加载失败：{plugins.message}
							</p>
						) : null}
						{pluginErrors.length > 0 ? (
							<div className="ext-row flex items-start gap-1.5 rounded-lg border border-danger/20 bg-danger/5 px-3 py-2">
								<AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
								<div className="text-[11px] leading-relaxed text-danger/90">
									{pluginErrors.map((e, i) => (
										<div key={i}>{e}</div>
									))}
								</div>
							</div>
						) : null}
						{!masterOn ? (
							<p className="rounded-lg bg-paper-deep px-3 py-2 text-[11px] text-mute">
								扩展层当前关闭：插件条目暂不生效。可在 .xeyo/settings.json 将 enabled_extensions 设为 true。
							</p>
						) : null}
						{pluginRows.length > 0 ? (
							<ul className="divide-y divide-line/40 overflow-hidden rounded-xl border border-line/50">
								{pluginRows.map((p, i) => (
									<PluginRow
										key={p.name}
										plugin={p}
										index={i}
										masterOn={masterOn}
										busy={busy}
										onToggle={onPluginToggle}
									/>
								))}
							</ul>
						) : (
							<EmptyHint
								icon={PackageOpen}
								title={q ? '没有匹配的插件。' : '未安装插件。'}
								hint="插件声明于 .xeyo/settings.json 或 ~/.xeyo/plugins。"
							/>
						)}
					</div>
				) : null}

				{tab === 'mcp' ? (
					<div className="space-y-2">
						{mcp && mcp.ok === false ? (
							<p className="rounded-lg bg-danger/5 px-3 py-2 text-[12px] text-danger">
								加载失败：{mcp.message}
							</p>
						) : null}
						{!masterOn ? (
							<p className="rounded-lg bg-paper-deep px-3 py-2 text-[11px] text-mute">
								扩展层当前关闭：MCP 服务器暂不启动。可在 .xeyo/settings.json 将 enabled_extensions 设为 true。
							</p>
						) : null}
						{mcpRows.length > 0 ? (
							<ul className="divide-y divide-line/40 overflow-hidden rounded-xl border border-line/50">
								{mcpRows.map((s, i) => (
									<McpRow
										key={s.id}
										server={s}
										index={i}
										masterOn={masterOn}
										busy={busy}
										onToggle={onMcpToggle}
										onApprove={onMcpApprove}
										onReload={onMcpReload}
									/>
								))}
							</ul>
						) : (
							<EmptyHint
								icon={Plus}
								title={q ? '没有匹配的 MCP。' : '未配置 MCP 服务器。'}
								hint="在 .xeyo/mcp.json 声明服务器后重启后端。"
							/>
						)}
					</div>
				) : null}

				{tab === 'skills' ? (
					<div className="space-y-2">
						{!masterOn ? (
							<p className="rounded-lg bg-paper-deep px-3 py-2 text-[11px] text-mute">
								扩展层当前关闭：技能暂不可用。可在 .xeyo/settings.json 将 enabled_extensions 设为 true。
							</p>
						) : null}
						{skillRows.length > 0 ? (
							<ul className="divide-y divide-line/40 overflow-hidden rounded-xl border border-line/50">
								{skillRows.map((x, i) => (
									<SkillRow
										key={x.name}
										name={x.name}
										info={x.info}
										index={i}
										explicitOff={
											explicitSkills[x.name]?.enabled === false
										}
										masterOn={masterOn}
										busy={busy}
										onToggle={onSkillToggle}
									/>
								))}
							</ul>
						) : (
							<EmptyHint
								icon={Wand2}
								title={q ? '没有匹配的技能。' : '未发现技能。'}
								hint="技能来自工作区 / 本机 / 插件三源（SKILL.md）。"
							/>
						)}
					</div>
				) : null}
				</div>
			</div>
		</div>
	);
}
