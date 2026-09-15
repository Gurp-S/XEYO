import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {AlertTriangle, Loader2, Play, RefreshCw, Square, Terminal} from 'lucide-react';
import {
	getLocalModels,
	setLocalModelSettings,
	startLocalModel,
	stopLocalModel,
	switchLocalModel,
	type LocalModelEntry,
	type LocalModelsSnapshot,
	type LocalModelState,
} from '@/lib/api';
import {useSettingsStore} from '@/stores/settingsStore';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';

/**
 * 本地模型（llama.cpp）：设置 → 模型与账号。
 *
 * 自包含组件：配置与进程态全走后端 `/v1/local-models`，不写 settingsStore 主表
 * （与 MemorySwitchesSetting 同款）——唯一例外是「添加为账号」，那一步本就是在
 * 造一个 provider='local' 的账号，必须落到账号表里。
 *
 * 为什么是单实例选择而不是"多选常驻"：显存。两支模型量化后约 2.8GB + 5.2GB，
 * 8GB 级显卡放不下常驻副本。所以这里是"选一支、跑一支"，切换 = 停旧起新。
 */

const STATE_LABEL: Record<LocalModelState, string> = {
	stopped: '已停止',
	starting: '启动中',
	running: '运行中',
	error: '错误',
};

const STATE_TONE: Record<LocalModelState, string> = {
	stopped: 'text-mute',
	starting: 'text-accent',
	running: 'text-accent',
	error: 'text-danger',
};

function fmtSize(bytes: number): string {
	if (!bytes) return '0';
	return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function fmtUptime(sec: number): string {
	const s = Math.max(0, Math.floor(sec));
	if (s < 60) return `${s}s`;
	if (s < 3600) return `${Math.floor(s / 60)}m${s % 60}s`;
	return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}m`;
}

/** 一支模型的参数摘要：参数量（MoE 标激活量）· 原生上下文 · 体积。 */
function modelSummary(m: LocalModelEntry): string {
	const params = m.active_params_b
		? `${m.params_b}B（${m.active_params_b}B 激活）`
		: `${m.params_b}B`;
	const ctx = m.native_ctx >= 1000 ? `${Math.round(m.native_ctx / 1000)}K` : `${m.native_ctx}`;
	return `${params} · ${ctx} 上下文 · ${fmtSize(m.size_bytes)}`;
}

export function LocalModelSetting({workspace}: {workspace?: string}) {
	const profiles = useSettingsStore(s => s.profiles) ?? [];
	const activeProfileId = useSettingsStore(s => s.activeProfileId);
	const addProfile = useSettingsStore(s => s.addProfile);
	const updateProfile = useSettingsStore(s => s.updateProfile);
	const selectProfile = useSettingsStore(s => s.selectProfile);

	const [snap, setSnap] = useState<LocalModelsSnapshot | null>(null);
	const [loaded, setLoaded] = useState(false);
	const [busy, setBusy] = useState<string | null>(null);
	const alive = useRef(true);

	const refresh = useCallback(async () => {
		const next = await getLocalModels(workspace);
		if (alive.current && next) setSnap(next);
		return next;
	}, [workspace]);

	useEffect(() => {
		alive.current = true;
		void (async () => {
			await refresh();
			if (alive.current) setLoaded(true);
		})();
		return () => {
			alive.current = false;
		};
	}, [refresh]);

	// 加载态需要密集轮询（模型加载十秒级起步），稳定后降到 10s。
	// 面板关闭即卸载，所以这里的常驻轮询有明确边界。
	const state = snap?.status.state;
	useEffect(() => {
		const period = state === 'starting' ? 2000 : 10000;
		const id = window.setInterval(() => {
			if (document.visibilityState === 'visible') void refresh();
		}, period);
		return () => window.clearInterval(id);
	}, [refresh, state]);

	const settings = snap?.settings;
	const status = snap?.status;
	const models = useMemo(() => snap?.models ?? [], [snap]);
	const activeModel = settings?.active_model ?? '';
	const activeEntry = models.find(m => m.id === activeModel);

	/** 所有写动作统一走这里：置忙 → 请求 → 用回执刷新 → 失败提示。 */
	const run = async (
		key: string,
		action: () => Promise<LocalModelsSnapshot | null>,
		fallbackError: string,
	) => {
		setBusy(key);
		const next = await action();
		setBusy(null);
		if (next) {
			setSnap(next);
			if (next.ok === false) {
				toast.error(next.error || fallbackError);
			}
		} else {
			toast.error(fallbackError);
		}
		return next;
	};

	const onToggleEnabled = async () => {
		if (!settings) return;
		const next = !settings.enabled;
		const r = await run(
			'gate',
			() => setLocalModelSettings({enabled: next}, workspace),
			'本地模型开关保存失败',
		);
		// 关掉开关 = 不再需要常驻，顺手停掉进程（"防止日常消耗"的那一半）。
		if (next && r?.settings.enabled) {
			await run('start', () => startLocalModel(activeModel, workspace), '本地模型启动失败');
		} else if (!next) {
			await run('stop', () => stopLocalModel(workspace), '本地模型停止失败');
		}
	};

	const onSelectModel = (id: string) => {
		if (id === activeModel) return;
		void run('switch', () => switchLocalModel(id, workspace), '模型切换失败');
	};

	const onStart = () =>
		void run('start', () => startLocalModel(activeModel, workspace), '本地模型启动失败');
	const onStop = () =>
		void run('stop', () => stopLocalModel(workspace), '本地模型停止失败');

	/** 把当前本地模型落成一个 provider='local' 的账号并切过去。 */
	const onUseAsAccount = () => {
		if (!snap || !activeEntry) return;
		const entry = activeEntry;
		const baseUrl = snap.base_url;
		const contextLimit = Math.max(1, Number(settings?.ctx) || 8192);
		const existing = profiles.find(p => p.provider === 'local');
		const payload = {
			provider: 'local' as const,
			name: '本地模型',
			note: entry.label,
			baseUrl,
			model: entry.id,
			// 本地服务不校验 Key；留空即可（allowsEmptyApiKey 对 'local' 恒放行）。
			apiKey: '',
			models: [
				{
					id: entry.id,
					contextLimit: Math.min(contextLimit, entry.native_ctx),
					inputType: 'text' as const,
					outputType: 'text' as const,
				},
			],
		};
		if (existing) {
			updateProfile(existing.id, payload);
			selectProfile(existing.id);
			toast.success(`已更新本地模型账号（${entry.label}）`);
			return;
		}
		const id = addProfile(payload);
		selectProfile(id);
		toast.success(`已添加本地模型账号（${entry.label}）`);
	};

	if (!loaded) {
		return (
			<div className="rounded-xl border border-line/70 bg-glass-strong px-3 py-2.5">
				<p className="text-[11px] text-mute">载入本地模型状态…</p>
			</div>
		);
	}

	if (!snap) {
		return (
			<div className="rounded-xl border border-line/70 bg-glass-strong px-3 py-2.5">
				<p className="text-[11px] text-mute">
					读取本地模型设置失败：后端未就绪或接口不可达。
				</p>
			</div>
		);
	}

	const starting = status?.state === 'starting';
	const running = status?.state === 'running';
	const presentOk = activeEntry?.present === true;
	const ready = snap.binary.found && presentOk;
	const localProfile = profiles.find(p => p.provider === 'local');
	const isActiveAccount =
		!!localProfile && activeProfileId === localProfile.id;

	return (
		<div className="space-y-2.5 rounded-xl border border-line/70 bg-glass-strong p-3">
			{/* 标题行 + 启用开关 */}
			<div className="flex items-start justify-between gap-3">
				<span className="min-w-0">
					<span className="block text-sm text-ink">本地模型</span>
					<span className="mt-0.5 block text-[11px] leading-snug text-mute">
						llama.cpp 在本机跑模型，不消耗 API 额度。一次只驻留一支模型，
						随 XEYO 启动而启动、关闭而关闭。
					</span>
				</span>
				<button
					type="button"
					disabled={busy === 'gate'}
					onClick={() => void onToggleEnabled()}
					aria-label={settings?.enabled ? '停用本地模型' : '启用本地模型'}
					title={settings?.enabled ? '停用本地模型' : '启用本地模型'}
					className={cn(
						'xy-press relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50',
						settings?.enabled ? 'bg-accent' : 'bg-line',
					)}
				>
					<span
						className={cn(
							'absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform',
							settings?.enabled ? 'translate-x-4' : 'translate-x-0',
						)}
					/>
				</button>
			</div>

			{/* 运行态 */}
			<div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-mute">
				<span className="inline-flex items-center gap-1.5">
					{busy ? (
						<Loader2 className="h-3 w-3 animate-spin text-accent" />
					) : (
						<span
							className={cn(
								'inline-block h-1.5 w-1.5 rounded-full',
								running ? 'bg-accent' : status?.state === 'error' ? 'bg-danger' : 'bg-line',
							)}
						/>
					)}
					<span className={cn(STATE_TONE[(status?.state ?? 'stopped') as LocalModelState])}>
						{STATE_LABEL[(status?.state ?? 'stopped') as LocalModelState]}
					</span>
					{starting ? <span>（首次加载需要等模型权重读进显存）</span> : null}
				</span>
				{running && status ? (
					<>
						<span className="font-mono">{status.base_url}</span>
						<span>PID {status.pid}</span>
						<span>{fmtUptime(status.uptime_s)}</span>
					</>
				) : null}
			</div>

			{status?.state === 'error' && status.error ? (
				<p className="text-[11px] leading-snug" style={{color: 'var(--xy-danger)'}}>
					{status.error}
					<span className="block font-mono text-[10px] text-mute">{status.log_path}</span>
				</p>
			) : null}

			{/* 依赖缺失提示（唯一需要离开 GUI 的动作） */}
			{!snap.binary.found ? (
				<div
					className="flex items-start gap-2 rounded-xl border px-3 py-2"
					style={{borderColor: 'var(--xy-danger)'}}
				>
					<AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
					<span className="min-w-0 text-[11px] leading-snug text-mute">
						未找到 llama-server。在仓库根执行下面这行把 llama.cpp 与权重一起拉下来：
						<span className="mt-1 flex items-center gap-1.5">
							<Terminal className="h-3 w-3 shrink-0 text-accent" />
							<code className="xy-surface min-w-0 break-all rounded-lg border border-line bg-paper-deep px-2 py-1 font-mono text-[10px] text-ink">
								py -3.11 scripts/fetch-local-models.py
							</code>
						</span>
						<span className="mt-1 block font-mono text-[10px]">
							{snap.models_dir}
						</span>
					</span>
				</div>
			) : null}

			{/* 模型选择（单实例） */}
			<div className="space-y-1.5">
				<span className="block text-[10px] uppercase tracking-wider text-mute">模型</span>
				{models.map(m => {
					const selected = m.id === activeModel;
					return (
						<button
							key={m.id}
							type="button"
							disabled={busy === 'switch'}
							onClick={() => onSelectModel(m.id)}
							className={cn(
								'xy-press flex w-full items-start gap-2.5 rounded-xl border px-3 py-2 text-left transition-colors disabled:opacity-50',
								selected
									? 'border-accent/50 bg-accent-soft'
									: 'border-line bg-glass-strong hover:border-line',
							)}
						>
							<span
								className={cn(
									'mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full border',
									selected ? 'border-accent bg-accent' : 'border-line',
								)}
							/>
							<span className="min-w-0 flex-1">
								<span className="flex items-center gap-2">
									<span
										className={cn(
											'truncate text-[12px]',
											selected ? 'text-accent' : 'text-ink',
										)}
									>
										{m.label}
									</span>
									<span
										className={cn(
											'shrink-0 text-[10px]',
											m.present ? 'text-mute' : 'text-danger',
										)}
									>
										{m.present
											? '已就绪'
											: m.downloaded_bytes > 0
												? `下载中 ${(m.downloaded_bytes / 1024 ** 3).toFixed(1)}/${fmtSize(m.size_bytes)}`
												: '缺失'}
									</span>
								</span>
								<span className="mt-0.5 block truncate text-[10px] text-mute">
									{modelSummary(m)}
								</span>
							</span>
						</button>
					);
				})}
			</div>

			{/* 动作 */}
			<div className="flex flex-wrap items-center gap-2">
				<button
					type="button"
					disabled={!!busy || running || starting || !ready}
					onClick={onStart}
					className={cn(
						'xy-press inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[12px] transition-colors disabled:opacity-50',
						'border-accent/50 bg-accent-soft text-accent',
					)}
				>
					<Play className="h-3.5 w-3.5" />
					启动
				</button>
				<button
					type="button"
					disabled={!!busy || !(running || starting)}
					onClick={onStop}
					className="xy-press inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-[12px] text-mute transition-colors hover:text-ink disabled:opacity-50"
				>
					<Square className="h-3.5 w-3.5" />
					停止并释放显存
				</button>
				<button
					type="button"
					disabled={!!busy}
					onClick={() => void refresh()}
					className="xy-press inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-[12px] text-mute transition-colors hover:text-ink disabled:opacity-50"
				>
					<RefreshCw className={cn('h-3.5 w-3.5', busy === 'refresh' && 'animate-spin')} />
					刷新
				</button>
				<button
					type="button"
					disabled={!!busy || !activeEntry}
					onClick={onUseAsAccount}
					title="把当前本地模型写成一个 provider=local 的账号并切过去，之后在输入框上拉即可选它"
					className={cn(
						'xy-press ml-auto inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[12px] transition-colors disabled:opacity-50',
						isActiveAccount
							? 'border-line text-mute'
							: 'border-accent/50 bg-accent-soft text-accent',
					)}
				>
					{isActiveAccount ? '已在用此账号' : '添加为账号'}
				</button>
			</div>

			{/* 参数（紧凑行；改了立即落盘） */}
			<div className="grid grid-cols-2 gap-2 border-t border-line/60 pt-2.5 sm:grid-cols-4">
				<NumField
					label="端口"
					value={settings?.port ?? 8080}
					min={1}
					max={65535}
					disabled={!!busy || running || starting}
					onCommit={v => void run('cfg', () => setLocalModelSettings({port: v}, workspace), '端口保存失败')}
				/>
				<NumField
					label="上下文"
					value={settings?.ctx ?? 8192}
					min={512}
					max={1_048_576}
					disabled={!!busy || running || starting}
					onCommit={v => void run('cfg', () => setLocalModelSettings({ctx: v}, workspace), '上下文保存失败')}
				/>
				<NumField
					label="GPU 层数"
					value={settings?.gpu_layers ?? 99}
					min={0}
					max={999}
					disabled={!!busy || running || starting}
					onCommit={v =>
						void run('cfg', () => setLocalModelSettings({gpu_layers: v}, workspace), 'GPU 层数保存失败')
					}
				/>
				<div className="flex min-w-0 flex-col">
					<span className="mb-1 block text-[10px] text-mute">可执行文件</span>
					<span
						className="truncate font-mono text-[10px] text-mute"
						title={snap.binary.path || '未找到'}
					>
						{snap.binary.found ? (snap.binary.path.split(/[\\/]/).pop() ?? '已找到') : '未找到'}
					</span>
				</div>
			</div>
			<p className="text-[10px] leading-snug text-mute">
				端口 / 上下文 / GPU 层数的改动在服务停止后生效；运行中改参数不会打断当前会话。
			</p>
		</div>
	);
}

/** 数字参数输入：本地草稿 + 失焦/回车提交，避免每敲一位就写盘。 */
function NumField({
	label,
	value,
	min,
	max,
	disabled,
	onCommit,
}: {
	label: string;
	value: number;
	min: number;
	max: number;
	disabled?: boolean;
	onCommit: (v: number) => void;
}) {
	const [draft, setDraft] = useState(String(value));
	const editing = useRef(false);
	useEffect(() => {
		if (!editing.current) setDraft(String(value));
	}, [value]);

	const commit = () => {
		editing.current = false;
		const n = Math.floor(Number(draft));
		if (!Number.isFinite(n) || n < min || n > max) {
			setDraft(String(value));
			return;
		}
		if (n !== value) onCommit(n);
		else setDraft(String(value));
	};

	return (
		<label className="flex min-w-0 flex-col">
			<span className="mb-1 block text-[10px] text-mute">{label}</span>
			<input
				type="number"
				min={min}
				max={max}
				disabled={disabled}
				value={draft}
				onFocus={() => {
					editing.current = true;
				}}
				onChange={e => setDraft(e.target.value)}
				onBlur={commit}
				onKeyDown={e => {
					if (e.key === 'Enter') e.currentTarget.blur();
				}}
				className="xy-surface w-full rounded-lg border border-line bg-glass-strong px-2 py-1 font-mono text-[11px] text-ink outline-none focus:border-accent disabled:opacity-50"
			/>
		</label>
	);
}
