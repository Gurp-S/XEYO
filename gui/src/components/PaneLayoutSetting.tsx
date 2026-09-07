import {useSettingsStore, PANE_LAYOUTS, type PaneLayout} from '@/stores/settingsStore';

/**
 * 面板布局与分割线选择（设置 → 外观）。
 * 四档：islands(圆角分岛,默认) / wireless(无线化) / dotted(虚点线) / classic(经典)。
 * 纯前端视觉档位：写 settingsStore.paneLayout → html[data-pane-layout]，
 * CSS 分发见 styles/pane-layouts.css；不触碰拖拽逻辑与布局测量。
 */

/** 迷你缩略示意：三栏 + 各档分割线画法（着色统一走主题 token）。 */
function Swatch({id}: {id: PaneLayout}) {
	const stroke = {
		fill: 'none',
		strokeWidth: 1.4,
	} as const;
	if (id === 'islands') {
		return (
			<g {...stroke}>
				<rect x="1.5" y="3.5" width="7" height="17" rx="3" />
				<rect x="12.5" y="3.5" width="15" height="17" rx="3" />
				<rect x="31.5" y="3.5" width="7" height="17" rx="3" />
			</g>
		);
	}
	if (id === 'wireless') {
		return (
			<g {...stroke}>
				<rect x="3" y="7" width="34" height="13" rx="5" />
			</g>
		);
	}
	if (id === 'dotted') {
		return (
			<g {...stroke}>
				<rect x="3" y="4" width="10" height="16" rx="2" />
				<rect x="27" y="4" width="10" height="16" rx="2" />
				<line x1="20" y1="6" x2="20" y2="18" strokeDasharray="1 2.4" strokeLinecap="round" />
			</g>
		);
	}
	return (
		<g {...stroke}>
			<rect x="3" y="4" width="10" height="16" rx="2" />
			<rect x="27" y="4" width="10" height="16" rx="2" />
			<line x1="20" y1="8" x2="20" y2="16" />
		</g>
	);
}

export function PaneLayoutSetting() {
	const paneLayout = useSettingsStore(s => s.paneLayout);
	const update = useSettingsStore(s => s.update);
	const cur = PANE_LAYOUTS.find(p => p.id === paneLayout) ?? PANE_LAYOUTS[0];

	return (
		<div className="space-y-2.5 rounded-xl border border-line/70 bg-glass-strong p-3">
			<div className="flex items-center justify-between">
				<span className="text-sm text-ink">面板布局与分割线</span>
				<span className="text-[11px] text-mute">{cur.hint}</span>
			</div>
			<div className="grid grid-cols-4 gap-1.5">
				{PANE_LAYOUTS.map(p => {
					const on = p.id === paneLayout;
					return (
						<button
							key={p.id}
							type="button"
							aria-pressed={on}
							title={p.hint}
							onClick={() => update({paneLayout: p.id})}
							className={cnCard(on)}
						>
							<svg viewBox="0 0 40 24" className="h-8 w-12" aria-hidden>
								<g
									stroke={on ? 'var(--xy-accent)' : 'var(--xy-mute)'}
									opacity={on ? 0.95 : 0.6}
								>
									<Swatch id={p.id} />
								</g>
							</svg>
							<span className="text-[11px]">{p.label}</span>
						</button>
					);
				})}
			</div>
			<div className="text-[11px] leading-snug text-mute">
				只改变分割与分界画法；侧栏 / 会话区 / 工作区宽度拖拽不受影响。悬停分割位置仍可拖动调宽。
			</div>
		</div>
	);
}

function cnCard(on: boolean): string {
	return [
		'xy-press flex flex-col items-center gap-1 rounded-lg border px-1 py-2 transition-colors',
		on ? 'border-accent/60 bg-accent-soft text-ink' : 'border-line bg-glass text-mute hover:border-line',
	].join(' ');
}
