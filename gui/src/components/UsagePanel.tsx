import {BarChart3, ChevronDown, Coins, CreditCard, Gift, LineChart, Wallet} from 'lucide-react';
import {useEffect, useId, useMemo, useRef, useState} from 'react';
import {UsageChart, type ChartKind, type ChartRow} from '@/components/UsageChart';
import {
	fetchUsage,
	fetchUsageBalance,
	fetchVendorModels,
	type UsageBalance,
	type UsageDayPoint,
	type UsageModelBlock,
	type UsageReport,
} from '@/lib/api';
import {PageShell} from '@/components/PageShell';
import {cn} from '@/lib/utils';
import {isLocalProvider} from '@/lib/localTestGate';
import {
	PROVIDER_LABEL,
	keyFingerprint,
	modelLabel,
	useSettingsStore,
	type ProviderId,
} from '@/stores/settingsStore';

const TOKEN_SERIES = [
	{
		key: 'cache_hit',
		label: '输入（命中缓存）',
		color: 'var(--xy-chart-soft)',
	},
	{
		key: 'cache_miss',
		label: '输入（未命中缓存）',
		color: 'var(--xy-chart-mid)',
	},
	{
		key: 'output',
		label: '输出',
		color: 'var(--xy-chart)',
	},
];

const COST_SERIES = [
	{key: 'cost', label: '消费金额', color: 'var(--xy-chart)'},
];
const REQ_SERIES = [
	{key: 'requests', label: '请求次数', color: 'var(--xy-chart)'},
];

function fmtCny(n: number): string {
	if (!Number.isFinite(n) || n === 0) {
		return '¥0';
	}
	if (n >= 1) {
		return `¥${n.toFixed(2)}`;
	}
	return `¥${n.toFixed(4)}`;
}

function fmtBalance(raw: string, currency?: string): string {
	const n = Number(raw);
	const unit = (currency || 'CNY').toUpperCase() === 'USD' ? '$' : '¥';
	if (!Number.isFinite(n)) {
		return `${unit}${raw}`;
	}
	return `${unit}${raw}`;
}

function costSourceHint(source?: string, costSource?: string): string {
	if (source === 'vendor') {
		return '金额与用量来自厂商官方接口（权威）';
	}
	if (source === 'mixed') {
		return '汇总以厂商为准；按模型拆分厂商未提供，已用本机记账补上';
	}
	if (source === 'local') {
		return '厂商未提供历史用量，以下为本机根据对话官方 usage 记账';
	}
	if (costSource === 'api') {
		return '金额来自接口 usage 字段';
	}
	if (costSource === 'mixed') {
		return '部分来自接口金额，其余按官方 token × 价目估算';
	}
	if (costSource === 'estimate') {
		return '金额按官方 token × 价目估算';
	}
	return '正在拉取用量';
}

function fmtInt(n: number): string {
	return Math.round(n).toLocaleString('en-US');
}

function fmtCompact(n: number): string {
	const abs = Math.abs(n);
	if (abs >= 1_000_000) {
		const v = n / 1_000_000;
		return `${v >= 10 || v <= -10 ? v.toFixed(0) : v.toFixed(1)}M`;
	}
	if (abs >= 1000) {
		const v = n / 1000;
		return `${v >= 10 || v <= -10 ? v.toFixed(0) : v.toFixed(1)}K`;
	}
	if (abs >= 1 || abs === 0) {
		return String(Math.round(n));
	}
	return n.toFixed(2);
}

function dayLabel(iso: string): string {
	const parts = iso.split('-');
	if (parts.length < 3) {
		return iso;
	}
	return `${Number(parts[1])}/${Number(parts[2])}`;
}

function toRows(
	series: UsageDayPoint[],
	pick: (p: UsageDayPoint) => Record<string, number>,
): ChartRow[] {
	return series.map(p => ({
		label: dayLabel(p.day),
		date: p.day,
		values: pick(p),
	}));
}

function providerName(id: string): string {
	return isProviderId(id) ? PROVIDER_LABEL[id] : id;
}

/** 合并多个厂商的用量（「全部」视图）：模型分块去重合并、系列按天累加、总额相加。 */
function mergeReports(reports: UsageReport[]): UsageReport {
	const totals = reports.reduce(
		(a, r) => ({
			cost: a.cost + (r.totals?.cost ?? 0),
			requests: a.requests + (r.totals?.requests ?? 0),
			tokens: a.tokens + (r.totals?.tokens ?? 0),
		}),
		{cost: 0, requests: 0, tokens: 0},
	);
	const lifetimeCost = reports.reduce((a, r) => a + (r.lifetime_cost ?? 0), 0);
	const seriesMap = new Map<string, UsageDayPoint>();
	for (const r of reports) {
		for (const p of r.series ?? []) {
			const cur =
				seriesMap.get(p.day) ??
				({day: p.day, cost: 0, requests: 0, tokens: 0, cache_hit: 0, cache_miss: 0, output: 0} as UsageDayPoint);
			cur.cost += p.cost;
			cur.requests += p.requests;
			cur.tokens += p.tokens;
			cur.cache_hit += p.cache_hit;
			cur.cache_miss += p.cache_miss;
			cur.output += p.output;
			seriesMap.set(p.day, cur);
		}
	}
	// 跨厂商去重 same provider+model 分块，避免重复计数。
	const modelMap = new Map<string, UsageModelBlock>();
	for (const m of reports.flatMap(r => r.models ?? [])) {
		const key = `${m.provider}:${m.model}`;
		const cur = modelMap.get(key) ?? {provider: m.provider, model: m.model, requests: 0, tokens: 0, cost: 0, series: []};
		cur.requests += m.requests;
		cur.tokens += m.tokens;
		cur.cost += m.cost;
		cur.series = mergeSeries(cur.series, m.series ?? []);
		modelMap.set(key, cur);
	}
	const models = [...modelMap.values()];
	return {
		days: reports[0]?.days ?? [],
		totals,
		lifetime_cost: lifetimeCost,
		cost_source: reports.some(r => r.cost_source === 'vendor')
			? 'vendor'
			: reports.some(r => r.cost_source === 'api')
				? 'api'
				: 'estimate',
		source: reports.some(r => r.source === 'vendor')
			? 'vendor'
			: reports.some(r => r.source === 'local')
				? 'local'
				: 'mixed',
		vendor_ok: reports.some(r => r.vendor_ok),
		series: [...seriesMap.values()],
		models,
		keys: reports.flatMap(r => r.keys ?? []),
	};
}

/** 按天累加合并两组日序列（保持原顺序）。 */
function mergeSeries(
	a: UsageDayPoint[],
	b: UsageDayPoint[],
): UsageDayPoint[] {
	const map = new Map<string, UsageDayPoint>();
	for (const p of [...a, ...b]) {
		const cur =
			map.get(p.day) ??
			({day: p.day, cost: 0, requests: 0, tokens: 0, cache_hit: 0, cache_miss: 0, output: 0} as UsageDayPoint);
		cur.cost += p.cost;
		cur.requests += p.requests;
		cur.tokens += p.tokens;
		cur.cache_hit += p.cache_hit;
		cur.cache_miss += p.cache_miss;
		cur.output += p.output;
		map.set(p.day, cur);
	}
	return [...map.values()];
}

function isProviderId(v: string): v is ProviderId {
	// 'local' 受 localTestGate 管理（T25c）。
	return v === 'deepseek' || v === 'openai' || isLocalProvider(v);
}

type Props = {
	/** 面板可见时拉数；keep-alive 隐藏时不刷。 */
	active?: boolean;
};

export function UsagePanel({active = true}: Props) {
	const profiles = useSettingsStore(s => s.profiles);
	const [days, setDays] = useState(30);
	const [modelId, setModelId] = useState('');
	const [keyFp, setKeyFp] = useState('');
	const [kind, setKind] = useState<ChartKind>('bar');
	const [openMenu, setOpenMenu] = useState<null | 'days' | 'key' | 'model'>(
		null,
	);
	const [report, setReport] = useState<UsageReport | null>(null);
	const [vendorModelIds, setVendorModelIds] = useState<string[]>([]);
	const [balance, setBalance] = useState<UsageBalance | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState('');

	// P2-⑨：给余额卡标注归属账号，消除「cost 跨厂商合计、余额却只显示单账号」的歧义。
	// 非 DeepSeek 厂商官方通常不提供 /user/balance，余额卡只对 DeepSeek 有效。
	const balanceOwner = useMemo(() => {
		const match = keyFp
			? profiles.find(p => keyFingerprint(p.apiKey) === keyFp)
			: profiles.find(p => p.apiKey.trim()) ?? null;
		const provider = match?.provider || useSettingsStore.getState().provider;
		const key = match?.apiKey || useSettingsStore.getState().apiKey;
		if (!key.trim() || provider !== 'deepseek') {
			return null;
		}
		const fp = keyFingerprint(key);
		return {
			provider,
			label: `${PROVIDER_LABEL[provider] ?? provider}${fp ? ` · ${fp.slice(0, 6)}` : ''}`,
		};
	}, [keyFp, profiles]);
	const filtersRef = useRef<HTMLDivElement>(null);
	const menuId = useId();

	useEffect(() => {
		if (!active) {
			return;
		}
		let cancelled = false;
		const load = (silent: boolean) => {
			if (!silent) {
				setLoading(true);
				setError('');
			}
			const match = keyFp
				? profiles.find(p => keyFingerprint(p.apiKey) === keyFp)
				: profiles.find(p => p.apiKey.trim()) ?? null;
			const s = useSettingsStore.getState();
			// 「全部」（未选 Key/模型）：按每个已配置的厂商分别拉取再合并，
			// 让用量页跨厂商展示，而不是只显示一个厂商（smoke-test #11）。
			if (!keyFp && !modelId) {
				const providers = [
					...new Set(
						profiles
							.filter(p => p.apiKey.trim())
							.map(p => p.provider),
					),
				];
				if (providers.length <= 1) {
					void fetchUsage({
						days,
						provider: match?.provider || s.provider,
						apiKey: match?.apiKey || s.apiKey,
						baseUrl: match?.baseUrl?.trim() || undefined,
					})
						.then(data => {
							if (!cancelled) {
								setReport(data);
							}
						})
						.catch(err => {
							if (!cancelled && !silent) {
								setError(err instanceof Error ? err.message : String(err));
								setReport(null);
							}
						})
						.finally(() => {
							if (!cancelled) {
								setLoading(false);
							}
						});
				} else {
					void (async () => {
						const results = await Promise.all(
							providers.map(prov => {
								const p = profiles.find(
									x => x.provider === prov && x.apiKey.trim(),
								);
								return fetchUsage({
									days,
									provider: prov,
									apiKey: p?.apiKey || s.apiKey,
									baseUrl: p?.baseUrl?.trim() || undefined,
								}).catch(() => null);
							}),
						);
						if (cancelled) {
							return;
						}
						const ok = results.filter(
							(r): r is UsageReport => Boolean(r),
						);
						if (ok.length > 0) {
							setReport(mergeReports(ok));
							setError('');
						} else {
							setError('没有可用的用量数据');
							setReport(null);
						}
						setLoading(false);
					})();
				}
				return;
			}
			void fetchUsage({
				days,
				model: modelId || undefined,
				key_fp: keyFp || undefined,
				provider: match?.provider || s.provider,
				apiKey: match?.apiKey || s.apiKey,
				baseUrl: match?.baseUrl?.trim() || undefined,
			})
				.then(data => {
					if (!cancelled) {
						setReport(data);
					}
				})
				.catch(err => {
					if (!cancelled && !silent) {
						setError(err instanceof Error ? err.message : String(err));
						setReport(null);
					}
				})
				.finally(() => {
					if (!cancelled) {
						setLoading(false);
					}
				});
		};
		load(false);
		const tick = window.setInterval(() => load(true), 20_000);
		const onVis = () => {
			if (document.visibilityState === 'visible') {
				load(true);
			}
		};
		window.addEventListener('focus', onVis);
		document.addEventListener('visibilitychange', onVis);
		return () => {
			cancelled = true;
			window.clearInterval(tick);
			window.removeEventListener('focus', onVis);
			document.removeEventListener('visibilitychange', onVis);
		};
	}, [active, days, modelId, keyFp, profiles]);

	useEffect(() => {
		if (!active) {
			return;
		}
		const match = keyFp
			? profiles.find(p => keyFingerprint(p.apiKey) === keyFp)
			: profiles.find(p => p.apiKey.trim()) ?? null;
		const key = match?.apiKey || useSettingsStore.getState().apiKey;
		const provider = match?.provider || useSettingsStore.getState().provider;
		if (!key.trim() || provider !== 'deepseek') {
			setBalance(null);
			return;
		}
		let cancelled = false;
		const load = () => {
			void fetchUsageBalance({
				apiKey: key,
				provider,
				baseUrl: match?.baseUrl,
			}).then(b => {
				if (!cancelled) {
					setBalance(b);
				}
			});
		};
		load();
		const tick = window.setInterval(load, 20_000);
		const onVis = () => {
			if (document.visibilityState === 'visible') {
				load();
			}
		};
		window.addEventListener('focus', onVis);
		document.addEventListener('visibilitychange', onVis);
		return () => {
			cancelled = true;
			window.clearInterval(tick);
			window.removeEventListener('focus', onVis);
			document.removeEventListener('visibilitychange', onVis);
		};
	}, [active, keyFp, profiles]);

	useEffect(() => {
		if (openMenu !== 'model') {
			return;
		}
		const match = keyFp
			? profiles.find(p => keyFingerprint(p.apiKey) === keyFp)
			: profiles.find(p => p.apiKey.trim()) ?? null;
		const s = useSettingsStore.getState();
		const key = match?.apiKey || s.apiKey;
		if (!key.trim()) {
			setVendorModelIds([]);
			return;
		}
		let cancelled = false;
		void fetchVendorModels({
			apiKey: key,
			provider: match?.provider || s.provider,
			baseUrl: match?.baseUrl?.trim() || undefined,
		}).then(rep => {
			if (!cancelled) {
				setVendorModelIds(rep.data.map(m => m.id));
			}
		});
		return () => {
			cancelled = true;
		};
	}, [openMenu, keyFp, profiles]);

	useEffect(() => {
		if (!openMenu) {
			return;
		}
		const onDoc = (e: MouseEvent) => {
			if (!filtersRef.current?.contains(e.target as Node)) {
				setOpenMenu(null);
			}
		};
		document.addEventListener('mousedown', onDoc);
		return () => document.removeEventListener('mousedown', onDoc);
	}, [openMenu]);

	const modelChoices = useMemo(() => {
		const seen = new Set<string>();
		const items: {id: string; label: string; hint: string}[] = [
			{id: '', label: '全部模型', hint: '厂商返回的全部模型'},
		];
		const add = (id: string, hint = '') => {
			if (!id || seen.has(id)) {
				return;
			}
			seen.add(id);
			items.push({id, label: modelLabel(id), hint: hint || id});
		};
		for (const id of vendorModelIds) {
			add(id, id);
		}
		for (const p of profiles) {
			if (p.model) {
				add(p.model, p.model);
			}
		}
		for (const m of report?.models ?? []) {
			add(m.model, m.model);
		}
		return items;
	}, [profiles, report, vendorModelIds]);

	const groups = useMemo(() => {
		const models = report?.models ?? [];
		let list = models;
		if (modelId) {
			const selected = models.find(m => m.model === modelId);
			if (selected) {
				list = models.filter(m => m.provider === selected.provider);
			} else {
				list = models.filter(m => m.model === modelId);
			}
		}
		const map = new Map<string, UsageModelBlock[]>();
		for (const m of list) {
			const arr = map.get(m.provider) ?? [];
			arr.push(m);
			map.set(m.provider, arr);
		}
		return [...map.entries()];
	}, [report, modelId]);

	const keys = useMemo(() => {
		// 只列设置里已配置的账号（profiles），与「设置 → 模型与账号」保持一致；
		// 用量 ledger 里的历史 key 只有指纹、无法还原成账号，不再出现在筛选项里。
		const set = new Set<string>();
		for (const p of profiles) {
			const fp = keyFingerprint(p.apiKey);
			if (fp) {
				set.add(fp);
			}
		}
		return [...set];
	}, [profiles]);

	useEffect(() => {
		if (keyFp && !keys.includes(keyFp)) {
			setKeyFp('');
		}
	}, [keyFp, keys]);

	const dayChoices = [
		{id: '1', label: '今日', hint: '今天'},
		{id: '7', label: '近 7 天', hint: '最近一周'},
		{id: '30', label: '近 30 天', hint: '最近一个月'},
		{id: '90', label: '近 90 天', hint: '最近一季度'},
	];
	const keyChoices = [
		{id: '', label: '全部', hint: '当前账号全部 Key'},
		...keys.map(k => ({id: k, label: k, hint: 'API Key'})),
	];
		const activeDay = dayChoices.find(d => d.id === String(days)) ?? dayChoices[2];
	const activeKey = keyChoices.find(k => k.id === keyFp) ?? keyChoices[0];
	const activeChoice = modelChoices.find(m => m.id === modelId) ?? modelChoices[0];

	const series = report?.series ?? [];
	const totals = report?.totals ?? {cost: 0, requests: 0, tokens: 0};
	const contentKey = `${days}:${keyFp}:${modelId}:${kind}`;

	const toolbar = (
		<>

				<FilterMenu
					label="时间"
					open={openMenu === 'days'}
					onToggle={() =>
						setOpenMenu(v => (v === 'days' ? null : 'days'))
					}
					valueLabel={activeDay.label}
					options={dayChoices}
					selectedId={String(days)}
					align="left"
					menuId={`${menuId}-days`}
					onSelect={id => {
						setDays(Number(id));
						setOpenMenu(null);
					}}
				/>
				<FilterMenu
					label="API Key"
					open={openMenu === 'key'}
					onToggle={() =>
						setOpenMenu(v => (v === 'key' ? null : 'key'))
					}
					valueLabel={activeKey.label}
					options={keyChoices}
					selectedId={keyFp}
					align="left"
					mono
					menuId={`${menuId}-key`}
					onSelect={id => {
						setKeyFp(id);
						setOpenMenu(null);
					}}
				/>
				<div className="ml-auto flex items-center gap-2">
					<div className="flex rounded-lg border border-line bg-glass-hover p-0.5">
						<button
							type="button"
							onClick={() => setKind('bar')}
							className={cn(
								'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px]',
								kind === 'bar'
									? 'bg-[var(--xy-chart-icon-bg)] text-[var(--xy-chart)]'
									: 'text-mute hover:text-ink',
							)}
						>
							<BarChart3 className="h-3 w-3" />
							柱状
						</button>
						<button
							type="button"
							onClick={() => setKind('line')}
							className={cn(
								'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px]',
								kind === 'line'
									? 'bg-[var(--xy-chart-icon-bg)] text-[var(--xy-chart)]'
									: 'text-mute hover:text-ink',
							)}
						>
							<LineChart className="h-3 w-3" />
							折线
						</button>
					</div>
					<FilterMenu
						open={openMenu === 'model'}
						onToggle={() =>
							setOpenMenu(v => (v === 'model' ? null : 'model'))
						}
						valueLabel={activeChoice.id ? activeChoice.id : '全部模型'}
						options={modelChoices.map(opt => ({
							id: opt.id,
							label: opt.id || '全部模型',
							hint: opt.label,
						}))}
						selectedId={modelId}
						align="right"
						mono
						menuId={`${menuId}-model`}
						onSelect={id => {
							setModelId(id);
							setOpenMenu(null);
						}}
					/>
				</div>
			
		</>
	);

	return (
		<PageShell
			wide
			toolbar={toolbar}
			toolbarRef={filtersRef}
			aria-busy={loading}
		>

						{loading && !report ? (
							<div className="xy-usage-loading pointer-events-none absolute inset-4 z-10">
								<div className="xy-usage-skeleton" />
								<div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
									<div className="xy-usage-skeleton min-h-[92px]" />
									<div className="xy-usage-skeleton min-h-[92px]" />
									<div className="xy-usage-skeleton min-h-[92px]" />
									<div className="xy-usage-skeleton min-h-[92px]" />
								</div>
								<div className="xy-usage-skeleton min-h-[240px]" />
							</div>
						) : null}
						<div key={contentKey} className="xy-usage-content-switch">
						{error ? (
						<p className="mb-3 rounded-xl border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
							{error}
							<span className="mt-1 block text-mute">
								请确认后端已启动，并在设置中填写可用的 API Key。
							</span>
						</p>
					) : null}
					{!error && report && report.source === 'local' ? (
						<p className="mb-3 rounded-xl border border-line bg-glass-hover px-3 py-2 text-[12px] text-ink-soft">
							厂商未提供可用的历史用量，已改用本机根据对话官方 usage
							记的账。余额仍来自官方接口。
						</p>
					) : null}
					{!error && report && report.source === 'mixed' ? (
						<p className="mb-3 rounded-xl border border-line bg-glass-hover px-3 py-2 text-[12px] text-ink-soft">
							汇总以厂商为准；按模型拆分厂商未返回，已用本机记账补上。
						</p>
					) : null}
					{!error &&
					report &&
					report.source === 'vendor' &&
					report.vendor_ok === false &&
					report.vendor_error ? (
						<p className="mb-3 rounded-xl border border-line bg-glass px-3 py-2 text-[12px] text-ink-soft">
							{report.vendor_error === 'missing_key'
								? '未提供 API Key，无法向厂商查询用量。'
								: report.vendor_error}
						</p>
					) : null}

					<div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 xy-usage-section">
						<SummaryCard
							label="余额"
							icon={Wallet}
							value={
								balance?.available && balance.total_balance != null
									? fmtBalance(balance.total_balance, balance.currency)
									: '—'
							}
							hint={
								// P2-⑨：明确余额归属账号，避免「全部」跨厂商合计却单账号余额的歧义。
								balanceOwner
									? `仅 ${balanceOwner.label}（非全部厂商合计）`
									: '仅 DeepSeek 账号 /user/balance'
							}
						/>
						<SummaryCard
							label="赠送额度"
							icon={Gift}
							value={
								balance?.available && balance.granted_balance != null
									? fmtBalance(balance.granted_balance, balance.currency)
									: '—'
							}
							hint="官方 granted_balance"
						/>
						<SummaryCard
							label="充值余额"
							icon={CreditCard}
							value={
								balance?.available && balance.topped_up_balance != null
									? fmtBalance(balance.topped_up_balance, balance.currency)
									: '—'
							}
							hint="官方 topped_up_balance"
						/>
						<SummaryCard
							label="请求 / Tokens"
							icon={Coins}
							value={`${fmtInt(totals.requests)} / ${fmtInt(totals.tokens)}`}
								hint={
									loading
										? '刷新中…'
										: report?.source === 'vendor'
											? '厂商用量汇总'
											: report?.source === 'mixed'
												? '厂商汇总 · 模型见本机'
												: '本机 usage 记账'
								}
						/>
					</div>

					<section className="xy-usage-section mb-4 rounded-xl border border-line bg-glass-hover px-4 pb-2 pt-3">
						<div className="mb-1 flex items-baseline justify-between gap-2">
							<div>
								<h3 className="text-[14px] font-medium text-ink">
									消费金额
								</h3>
								<p className="text-[11px] text-mute">
									{costSourceHint(report?.source, report?.cost_source)}
								</p>
							</div>
							<span className="text-[13px] tabular-nums text-ink-soft">
								{fmtCny(totals.cost)}
							</span>
						</div>
						<UsageChart
							rows={toRows(series, p => ({cost: p.cost}))}
							series={COST_SERIES}
							kind={kind}
							stacked
							height={200}
							formatY={fmtCompact}
							formatTotal={fmtCny}
							emptyText="暂无消费记录"
						/>
					</section>

					{groups.length === 0 ? (
						<p className="px-1 py-8 text-center text-[13px] text-mute">
							厂商未返回按模型拆分，本机也还没有对话记账。聊过天之后会按官方
							usage 写入本机；余额仍来自官方 /user/balance。
						</p>
					) : (
						groups.map(([provider, models]) => (
							<section key={provider} className="xy-usage-section mb-5">
								<h3 className="mb-2 px-1 text-[12px] font-medium tracking-wide text-mute">
									{providerName(provider)}
								</h3>
								<div className="flex flex-col gap-3">
									{models.map(block => (
										<ModelUsageRow
											key={`${block.provider}:${block.model}`}
											block={block}
											kind={kind}
											highlight={modelId === block.model}
										/>
									))}
								</div>
							</section>
						))
						)}
						</div>
		</PageShell>
	);
	}

function SummaryCard({
	label,
	value,
	hint,
	icon: Icon,
}: {
	label: string;
	value: string;
	hint: string;
	icon: typeof Wallet;
}) {
	return (
		<div className="xy-usage-card flex items-center gap-3 rounded-xl border border-line bg-glass-hover px-3.5 py-3.5">
			<div
				className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg"
				style={{background: 'var(--xy-chart-icon-bg)'}}
			>
				<Icon className="h-5 w-5" style={{color: 'var(--xy-chart-icon)'}} />
			</div>
			<div className="min-w-0">
				<div className="text-[11px] uppercase tracking-wide text-mute">
					{label}
				</div>
				<div className="mt-0.5 truncate text-[20px] font-semibold tabular-nums leading-tight text-ink">
					{value}
				</div>
				<div className="mt-0.5 text-[10px] text-mute">{hint}</div>
			</div>
		</div>
	);
}

function ModelUsageRow({
	block,
	kind,
	highlight,
}: {
	block: UsageModelBlock;
	kind: ChartKind;
	highlight: boolean;
}) {
	return (
		<div
className={cn(
						'xy-usage-row rounded-xl border px-2 py-2 sm:px-3',
				highlight
					? 'border-[color-mix(in_srgb,var(--xy-chart)_35%,var(--xy-line))] bg-glass-hover'
					: 'border-line bg-glass-hover',
			)}
		>
			<div className="mb-1 flex items-baseline justify-between px-2 pt-1">
				<div>
					<div className="font-mono text-[12px] text-ink">{block.model}</div>
				</div>
				<div className="text-[12px] tabular-nums text-mute">
					{fmtCny(block.cost)}
				</div>
			</div>
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
				<div className="rounded-xl border border-line bg-glass-hover px-3 pb-1 pt-2.5">
					<div className="mb-0.5 flex items-baseline justify-between">
						<span className="text-[13px] font-medium text-ink">API 请求次数</span>
						<span className="text-[13px] tabular-nums text-ink-soft">
							{fmtInt(block.requests)}
						</span>
					</div>
					<UsageChart
						rows={toRows(block.series, p => ({requests: p.requests}))}
						series={REQ_SERIES}
						kind={kind}
						height={148}
						formatY={fmtCompact}
						formatTotal={fmtInt}
					/>
				</div>
				<div className="rounded-xl border border-line bg-glass-hover px-3 pb-1 pt-2.5">
					<div className="mb-0.5 flex items-baseline justify-between">
						<span className="text-[13px] font-medium text-ink">Tokens</span>
						<span className="text-[13px] tabular-nums text-ink-soft">
							{fmtInt(block.tokens)}
						</span>
					</div>
					<UsageChart
						rows={toRows(block.series, p => ({
							cache_hit: p.cache_hit,
							cache_miss: p.cache_miss,
							output: p.output,
						}))}
						series={TOKEN_SERIES}
						kind={kind}
						stacked
						height={148}
						formatY={fmtCompact}
						formatTotal={fmtInt}
					/>
				</div>
			</div>
		</div>
	);
}

function FilterMenu({
	label,
	open,
	onToggle,
	valueLabel,
	options,
	selectedId,
	onSelect,
	align = 'left',
	mono = false,
	menuId,
}: {
	label?: string;
	open: boolean;
	onToggle: () => void;
	valueLabel: string;
	options: {id: string; label: string; hint?: string}[];
	selectedId: string;
	onSelect: (id: string) => void;
	align?: 'left' | 'right';
	mono?: boolean;
	menuId: string;
}) {
	return (
		<div className="flex items-center gap-1.5 text-[12px] text-mute">
			{label ? <span>{label}</span> : null}
			<div className="relative">
				<button
					type="button"
					aria-haspopup="listbox"
					aria-expanded={open}
					aria-controls={menuId}
					onClick={onToggle}
					className={cn(
						'inline-flex h-8 max-w-[14rem] items-center gap-1 rounded-lg px-2 text-[12px] text-ink-soft',
						mono && 'font-mono',
						'hover:bg-glass-hover hover:text-ink',
						open && 'bg-glass-hover text-ink',
					)}
				>
					<span className="truncate">{valueLabel}</span>
					<ChevronDown
						className={cn(
							'h-3 w-3 shrink-0 opacity-50 transition-transform',
							open && 'rotate-180 opacity-70',
						)}
					/>
				</button>
				{open ? (
					<ul
						id={menuId}
						role="listbox"
						className={cn(
							'xy-menu-flyout absolute top-full z-50 mt-1 max-h-72 min-w-[13rem] overflow-y-auto rounded-xl border border-line/50 py-1',
							align === 'right' ? 'right-0' : 'left-0',
						)}
					>
					{options.map(opt => {
						const active = opt.id === selectedId;
						return (
							<li
								key={opt.id || 'all'}
								role="option"
								aria-selected={active}
							>
								<button
									type="button"
									onClick={() => onSelect(opt.id)}
									className={cn(
										'xy-menu-row flex w-full flex-col items-start px-3 py-1.5 text-left',
										active ? 'is-active text-ink' : 'text-ink-soft',
									)}
								>
									<span className={cn('text-[12px]', mono && 'font-mono')}>
										{opt.label}
									</span>
									{opt.hint ? (
										<span className="text-[10px] text-mute">{opt.hint}</span>
									) : null}
								</button>
							</li>
						);
					})}
				</ul>
				) : null}
			</div>
		</div>
	);
}
