import {useEffect, useState} from 'react';
import {getMemorySwitches, runMemorySnapshot, setMemorySwitches, type MemorySwitch} from '@/lib/api';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';

/**
 * 记忆系统开关：读取后端 /v1/settings/memory，逐项切换并实时写盘 + 生效。
 *
 * 只渲染后端标了 `exposed` 的开关——其余（L5 模式 / 工具结果老化 / Memory 索引常驻注入）
 * 是测试与评测的便捷开关，仅后端可切，不在产品面板暴露。
 *
 * 开关态一律取 `effective`（运行时真值）而非 `value`（settings 里的字面值）：已下线/恒关
 * 占位键的 `effective` 恒为默认、`source` 报 `ignored`，因此不会再出现「显示开、实际关」。
 * 与 RuntimePresetSetting 同款：自包含组件，不动 settingsStore 主表。
 */
export function MemorySwitchesSetting() {
	const [items, setItems] = useState<Record<string, MemorySwitch>>({});
	const [stale, setStale] = useState<string[]>([]);
	const [busy, setBusy] = useState<string | null>(null);
	const [loaded, setLoaded] = useState(false);
	const [pruning, setPruning] = useState(false);

	useEffect(() => {
		let ok = true;
		(async () => {
			const r = await getMemorySwitches();
			if (!ok) return;
			if (r?.ok && r.switches) {
				setItems(r.switches);
				setStale(r.stale ?? []);
			}
			setLoaded(true);
		})();
		return () => {
			ok = false;
		};
	}, []);

	const onToggle = async (key: string, next: string) => {
		setBusy(key);
		const r = await setMemorySwitches({[key]: next});
		setBusy(null);
		if (r?.ok && r.switches) {
			setItems(r.switches);
			setStale(r.stale ?? []);
		} else {
			toast.error(r?.message || '记忆开关更新失败');
		}
	};

	/** 清理已失效的残留键：后端 save/prune 会把它们从 settings.memory 删掉。 */
	const onPrune = async () => {
		setPruning(true);
		const r = await setMemorySwitches({});
		setPruning(false);
		if (r?.ok && r.switches) {
			setItems(r.switches);
			setStale(r.stale ?? []);
			const n = r.pruned?.length ?? 0;
			if (n > 0) toast.success(`已清理 ${n} 个残留开关`);
		} else {
			toast.error(r?.message || r?.error || '清理残留开关失败');
		}
	};

	if (!loaded) {
		return <p className="text-[11px] text-mute">载入记忆系统开关…</p>;
	}

	// 仅 GUI 暴露项；effective 缺失时回退 value（旧后端兼容）。
	const rows = Object.values(items).filter(sw => sw.exposed === true);

	return (
		<div className="space-y-2">
			{rows.length === 0 ? (
				<p className="text-[11px] text-mute">当前无产品可切换的记忆开关（后端未就绪或均为测试开关）。</p>
			) : null}

			{rows.map(sw => {
				const current = sw.effective ?? sw.value;
				const isBinary = sw.allowed.length === 2 && sw.allowed.every(a => a === '0' || a === '1');
				const on = isBinary ? current === '1' : current === sw.allowed[sw.allowed.length - 1];
				const ignored = sw.ignored === true;
				const busyKey = busy === sw.key;
				return (
					<button
						key={sw.key}
						type="button"
						disabled={busyKey || ignored}
						onClick={() => {
							const next = isBinary ? (on ? '0' : '1') : on ? sw.allowed[0] : sw.allowed[sw.allowed.length - 1];
							void onToggle(sw.key, next);
						}}
						className={cn(
							'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors disabled:opacity-50',
							on ? 'border-accent/50 bg-accent-soft' : 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span>
							<span className="block text-sm text-ink">{sw.key.replace(/^XEYO_/, '')}</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">{sw.label}</span>
							<span className="mt-0.5 block text-[10px] text-mute">
								当前: {current}
								{ignored ? '（已下线，不生效）' : `（${sw.source}）`}
							</span>
						</span>
						<span
							className={cn(
								'relative h-5 w-9 shrink-0 rounded-full transition-colors',
								on ? 'bg-accent' : 'bg-line',
							)}
							aria-hidden
						>
							<span
								className={cn(
									'absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform',
									on ? 'translate-x-4' : 'translate-x-0',
								)}
							/>
						</span>
					</button>
				);
			})}

			{stale.length > 0 ? (
				<div className="rounded-xl border border-line/70 bg-glass-strong px-3 py-2.5">
					<div className="flex items-center justify-between gap-3">
						<span>
							<span className="block text-sm text-ink">已失效的残留开关（{stale.length}）</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">
								这些键已从开关注册表移除、运行时不再读取；留着会在同名键将来复活时静默继承旧值。
							</span>
							<span className="mt-0.5 block font-mono text-[10px] leading-snug text-mute">
								{stale.join(' · ')}
							</span>
						</span>
						<button
							type="button"
							disabled={pruning}
							onClick={() => void onPrune()}
							className={cn(
								'xy-press shrink-0 rounded-lg border px-3 py-1.5 text-xs transition-colors disabled:opacity-50',
								pruning ? 'opacity-60' : 'border-accent/50 bg-accent-soft text-accent',
							)}
						>
							{pruning ? '清理中…' : '立即清理'}
						</button>
					</div>
				</div>
			) : null}

			<A3SnapshotRow />
		</div>
	);
}

/** A3 日常监控：手动立即快照（按天去重，与每日自动任务写同一处证据）。 */
function A3SnapshotRow() {
	const [running, setRunning] = useState(false);
	const [result, setResult] = useState<string | null>(null);

	const onRun = async () => {
		setRunning(true);
		setResult(null);
		const r = await runMemorySnapshot();
		setRunning(false);
		if (r?.ok) {
			setResult(`快照完成 · ${r.day ?? ''}（同日重复点按天去重，不新增）`);
		} else {
			toast.error(r?.error || 'A3 快照失败');
		}
	};

	return (
		<div className="rounded-xl border border-line/70 bg-glass-strong px-3 py-2.5">
			<div className="flex items-center justify-between gap-3">
				<span>
					<span className="block text-sm text-ink">A3 日常监控快照</span>
					<span className="mt-0.5 block text-[11px] leading-snug text-mute">
						点按立即快照（读生产 ledger，写 docs/12 表D，无模型调用）。
						默认每天 09:30 由本地计划任务自动执行。
					</span>
				</span>
				<button
					type="button"
					disabled={running}
					onClick={() => void onRun()}
					className={cn(
						'xy-press shrink-0 rounded-lg border px-3 py-1.5 text-xs transition-colors disabled:opacity-50',
						running ? 'opacity-60' : 'border-accent/50 bg-accent-soft text-accent',
					)}
				>
					{running ? '快照中…' : '立即快照'}
				</button>
			</div>
			{result ? <p className="mt-1.5 text-[10px] text-mute">{result}</p> : null}
		</div>
	);
}
