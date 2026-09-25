import {useEffect, useState} from 'react';
import {loadBashPolicy, saveBashPolicy, type BashPolicy} from '@/lib/api';
import {samePath} from '@/lib/paths';
import {useChatStore} from '@/stores/chatStore';
import {toast} from '@/lib/toast';

/**
 * 43 号：Bash 专用工具路由 / 渐进强制设置（写工作区策略 .xeyo-policy.json）。
 * - 透明路由：auto=自动路由到 Read/Grep（区内）；off=报错提示。
 * - 重复放行次数 bash_escalate：0=关；同会话同命令形状重复命中 ≥ 该次数后放行 bash。
 *   UI 显示推荐值 escalate_recommended（=3）与上限 escalate_max（=5）。
 *
 * 用法：在 SettingsModal 的某个设置区渲染 <BashRoutingSetting /> 即可（独立组件，
 * 不影响现有构建；未导入前不会被 vite 打包）。
 */
export function BashRoutingSetting() {
	const root = useChatStore(s => {
		const space = s.spaces.find(item => item.id === s.activeSpaceId);
		return space?.rootPath?.trim() ?? '';
	});
	const [pol, setPol] = useState<BashPolicy | null>(null);
	const [routing, setRouting] = useState<'auto' | 'off'>('off');
	const [escalate, setEscalate] = useState(0);
	const [saved, setSaved] = useState(false);
	const [loadError, setLoadError] = useState(false);
	const [reloadKey, setReloadKey] = useState(0);

	useEffect(() => {
		let alive = true;
		setPol(null);
		setLoadError(false);
		if (!root) return () => { alive = false; };
		void loadBashPolicy(root).then(p => {
			if (!alive) return;
			if (!p) {
				setLoadError(true);
				return;
			}
			setPol(p);
			setRouting(p.bash_routing);
			setEscalate(p.bash_escalate);
		});
		return () => {
			alive = false;
		};
	}, [root, reloadKey]);

	async function save() {
		if (!root) return;
		const savedRoot = root;
		try {
			const p = await saveBashPolicy({
				bash_routing: routing,
				bash_escalate: escalate,
				workspace: savedRoot,
			});
			const state = useChatStore.getState();
			const currentRoot = state.spaces.find(item => item.id === state.activeSpaceId)?.rootPath?.trim() ?? '';
			if (!p) {
				if (samePath(savedRoot, currentRoot)) toast.error('Bash 策略保存失败');
				return;
			}
			if (samePath(savedRoot, currentRoot)) {
				setPol(p);
				setEscalate(p.bash_escalate);
				setRouting(p.bash_routing);
				setSaved(true);
				setTimeout(() => setSaved(false), 1500);
			}
		} catch (error) {
			const state = useChatStore.getState();
			const currentRoot = state.spaces.find(item => item.id === state.activeSpaceId)?.rootPath?.trim() ?? '';
			if (samePath(savedRoot, currentRoot)) {
				toast.error(error instanceof Error ? error.message : 'Bash 策略保存失败');
			}
		}
	}

	const max = pol?.escalate_max ?? 5;
	const recommended = pol?.escalate_recommended ?? 3;

	return (
		<div className="space-y-2 p-1">
			<div className="text-[11px] font-semibold text-ink">Bash 工具策略</div>
			{!root ? <div className="text-[10px] text-mute">打开工作区后可配置</div> : null}
			{root && !pol && !loadError ? <div className="text-[10px] text-mute">读取中…</div> : null}
			{root && loadError ? (
				<div className="flex items-center gap-2 text-[10px] text-mute">
					<span>读取失败</span>
					<button type="button" className="text-accent hover:underline" onClick={() => setReloadKey(key => key + 1)}>
						重试
					</button>
				</div>
			) : null}
			<label className="flex items-center justify-between gap-3">
				<span className="text-xs text-mute">透明路由</span>
				<select
					value={routing}
					onChange={e => setRouting(e.target.value as 'auto' | 'off')}
					className="xy-surface rounded-lg border border-line bg-glass-strong px-2 py-1 text-xs text-ink outline-none focus:border-accent"
				>
					<option value="off">off（报错提示）</option>
					<option value="auto">auto（自动路由）</option>
				</select>
			</label>
			<label className="flex items-center justify-between gap-3">
				<span className="text-xs text-mute">重复放行次数（0=关；推荐 {recommended}）</span>
				<input
					type="number"
					min={0}
					max={max}
					value={escalate}
					onChange={e => {
						const n = Number(e.target.value);
						setEscalate(
							Number.isFinite(n)
								? Math.max(0, Math.min(max, Math.trunc(n)))
								: 0,
						);
					}}
					className="xy-surface w-20 rounded-lg border border-line bg-glass-strong px-2 py-1 text-right text-xs text-ink outline-none focus:border-accent"
				/>
			</label>
			<div className="text-[10px] text-mute">
				同一命令与工具重复命中达到该次数后放行 bash 执行（不再报错）；上限 {max}。
			</div>
			<button
				onClick={save}
				disabled={!root || !pol}
				className="rounded-lg border border-line px-2 py-1 text-xs text-ink hover:border-accent"
			>
				{saved ? '已保存' : '保存'}
			</button>
		</div>
	);
}
