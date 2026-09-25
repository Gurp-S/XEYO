import {useEffect, useRef, useState} from 'react';

import {
	fetchSessionRuntimePreset,
	setSessionRuntimePreset,
} from '@/lib/api/runtimePreset';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';
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
	// 非空 = 这一档现在是"读不出"，内容就是原因。空串只代表"确实读到了"。
	const [unknown, setUnknown] = useState('');
	const [saved, setSaved] = useState(false);
	// 连点时只有最新一次切换的回执能改选中态，旧回执不得把它回滚掉。
	const seq = useRef(0);

	useEffect(() => {
		let alive = true;
		setLive(null);
		setUnknown('');
		if (!activeId) {
			setUnknown('no_active_session');
			return;
		}
		void fetchSessionRuntimePreset(activeId).then(r => {
			if (!alive) {
				return;
			}
			if (r.ok) {
				setLive(r.preset);
			} else {
				setUnknown(r.message || 'unknown');
			}
		});
		return () => {
			alive = false;
		};
	}, [activeId]);

	const select = (id: (typeof PRESETS)[number]['id']) => {
		const prev = live;
		const mySeq = ++seq.current;
		setLive(id);
		setSaved(false);
		if (!activeId) {
			return;
		}
		void setSessionRuntimePreset(activeId, id).then(res => {
			if (seq.current !== mySeq) {
				return; // 更新的切换已接管，旧回执不得回滚它
			}
			if (!res.ok) {
				// 权限面的"已生效"只能来自后端回执：403/422 时引擎仍按旧 preset 判定，
				// 留一个假的安全姿态比不切换更危险。
				setLive(prev);
				toast.error(`切换未生效：${res.message}`);
				return;
			}
			// 写回执同样是活值：它把"读不出"变成"知道是哪一档"。
			setUnknown('');
			setSaved(true);
			window.setTimeout(() => setSaved(false), 1500);
		});
	};

	return (
		<div className="space-y-2 p-1">
			<div className="text-[11px] font-semibold text-ink">
				会话权限 preset（本会话实时生效）
			</div>
			{unknown ? (
				<div
					role="status"
					className="rounded-lg border border-warn/60 bg-warn/10 px-2.5 py-1.5 text-[11px] leading-snug text-warn"
				>
					未能读取本会话当前的 preset（原因：{unknown}）。
					下面没有任何选中项，只代表没读到，不代表它没有生效值。
				</div>
			) : live === null ? (
				<div role="status" className="text-[11px] leading-snug text-mute">
					已确认本会话未显式切换过 preset，当前沿用创建时钉死的那一档。
				</div>
			) : null}
			{PRESETS.map(item => {
				const selected = live === item.id;
				return (
					<button
						key={item.id}
						type="button"
						onClick={() => select(item.id)}
						aria-pressed={selected}
						className={cn(
							'xy-press flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors',
							selected
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span
							aria-hidden
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
