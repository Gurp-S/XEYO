import {useEffect, useState} from 'react';

import {
	fetchSessionRuntimePreset,
	setSessionRuntimePreset,
} from '@/lib/api/runtimePreset';
import {cn} from '@/lib/utils';
import {useChatUiStore} from '@/stores/chatUiStore';

const PRESETS: Array<{
	id: 'readonly' | 'workspace-write' | 'full';
	label: string;
	desc: string;
}> = [
	{
		id: 'readonly',
		label: '只读',
		desc: '只读工具白名单；写/外发全部需要批准',
	},
	{
		id: 'workspace-write',
		label: '工作区写',
		desc: '工作区内安全写自动放行（默认）；风险操作需批准',
	},
	{
		id: 'full',
		label: '完全',
		desc: '工作区内外读写免确认（硬保护仍拦）',
	},
];

/**
 * smoke-test #6：会话权限 preset 实时切换。
 * 会话创建时 pin 的 preset 仅为默认值；此处切换立即写入后端运行时活值，
 * 后续轮次/工具调用即按新 preset 判定（收紧/放宽都即时）。
 */
export function RuntimePresetSetting() {
	const activeId = useChatUiStore(s => s.activeId);
	const [live, setLive] = useState<string | null>(null);
	const [saved, setSaved] = useState(false);

	useEffect(() => {
		let alive = true;
		setLive(null);
		if (!activeId) {
			return;
		}
		void fetchSessionRuntimePreset(activeId).then(v => {
			if (alive) {
				setLive(v);
			}
		});
		return () => {
			alive = false;
		};
	}, [activeId]);

	const select = (id: (typeof PRESETS)[number]['id']) => {
		setLive(id);
		setSaved(false);
		if (activeId) {
			setSessionRuntimePreset(activeId, id);
		}
		setSaved(true);
		window.setTimeout(() => setSaved(false), 1500);
	};

	return (
		<div className="space-y-2 p-1">
			<div className="text-[11px] font-semibold text-ink">
				会话权限 preset（本会话实时生效）
			</div>
			{PRESETS.map(item => {
				const selected = live === item.id;
				return (
					<button
						key={item.id}
						type="button"
						onClick={() => select(item.id)}
						className={cn(
							'xy-press flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors',
							selected
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span
							className={cn(
								'mt-0.5 h-3 w-3 shrink-0 rounded-full border',
								selected
									? 'border-accent bg-accent'
									: 'border-mute/50',
							)}
						/>
						<span className="min-w-0 flex-1">
							<span className="block text-[12px] font-medium text-ink">
								{item.label}
							</span>
							<span className="block text-[11px] leading-snug text-mute">
								{item.desc}
							</span>
						</span>
						{selected ? (
							<span className="shrink-0 text-[10px] text-accent">
								{saved ? '已生效' : '本会话'}
							</span>
						) : null}
					</button>
				);
			})}
			<div className="text-[10px] leading-relaxed text-mute">
				说明：切换立即写入后端并向本会话后续工具调用生效，不溯及已执行轮次；
				未显式切换的会话仍沿用创建时钉死的 preset。
			</div>
		</div>
	);
}
