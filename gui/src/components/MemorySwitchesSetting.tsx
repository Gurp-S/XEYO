import {useEffect, useState} from 'react';
import {getMemorySwitches, runMemorySnapshot, setMemorySwitches, type MemorySwitch} from '@/lib/api';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';

/**
 * 记忆系统开关：读取后端 /v1/settings/memory，逐项切换并实时写盘 + 生效。
 * 与 RuntimePresetSetting 同款：自包含组件，不动 settingsStore 主表。
 */
export function MemorySwitchesSetting() {
	const [items, setItems] = useState<Record<string, MemorySwitch>>({});
	const [busy, setBusy] = useState<string | null>(null);
	const [loaded, setLoaded] = useState(false);

	useEffect(() => {
		let ok = true;
		(async () => {
			const r = await getMemorySwitches();
			if (!ok) return;
			if (r?.ok && r.switches) {
				setItems(r.switches);
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
		} else {
			toast.error(r?.message || '记忆开关更新失败');
		}
	};

	if (!loaded) {
		return <p className="text-[11px] text-mute">载入记忆系统开关…</p>;
	}

	const rows = Object.values(items);
	if (rows.length === 0) {
		return <p className="text-[11px] text-mute">无可用记忆开关（后端未就绪）</p>;
	}

	return (
		<div className="space-y-2">
			{rows.map(sw => {
				const isBinary = sw.allowed.length === 2 && sw.allowed.every(a => a === '0' || a === '1');
				const on = isBinary ? sw.value === '1' : sw.value === sw.allowed[sw.allowed.length - 1];
				const busyKey = busy === sw.key;
				return (
					<button
						key={sw.key}
						type="button"
						disabled={busyKey}
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
								当前: {sw.value}（{sw.source}）
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
