import {Check, ChevronDown, Search} from 'lucide-react';
import {useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {cn} from '@/lib/utils';
import {useAnchoredPanel} from '@/ui/useAnchoredPanel';
import {useDismiss} from '@/ui/useDismiss';
import {
	REASONING_EFFORTS,
	type ReasoningEffort,
} from '@/stores/settingsStore';

/**
 * 思考等级多选下拉（设置页 · 模型行内）。
 *
 * 对齐历史 ModelPicker 的 flyout 视觉：搜索框 + 勾选行（Check 图标）。
 * 多选不自动收起；Portal 定位避免被设置弹层的滚动容器裁剪。
 */

/** 估高：低于它就不翻转（沿用重构前的常数，不借重构改几何）。 */
const EST_H = 320;
/** 面板最小宽 = 14ch；与历史一致。 */
const MIN_W_CH = 14;
const FLYOUT_ID = 'xeyo-reasoning-levels-flyout';

export function ReasoningLevelsSelect({
	value,
	onChange,
	placeholder = '未选择（不限）',
	ariaLabel = '思考等级',
}: {
	value: ReasoningEffort[];
	onChange: (next: ReasoningEffort[]) => void;
	placeholder?: string;
	ariaLabel?: string;
}) {
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState('');
	const wrapRef = useRef<HTMLDivElement>(null);
	const btnRef = useRef<HTMLButtonElement>(null);

	// 定位公式留在宿主（它是这一家自己的几何），监听与重算走全局回路。
	const panelStyle = useAnchoredPanel({
		open,
		anchorRef: btnRef,
		place: (r, vp) => {
			const width = Math.max(r.width, MIN_W_CH * 16);
			const left = Math.min(r.left, vp.width - width - 8);
			// 下方放不下则翻转到触发器上方。
			const below = r.bottom + EST_H < vp.height || r.top < EST_H;
			return {
				top: below ? r.bottom + 6 : Math.max(8, r.top - EST_H - 6),
				left: Math.max(8, left),
				minWidth: width,
			};
		},
	});

	// 思考等级下拉的 Esc 走 escStack 顶层：window 冒泡监听在流式期间会被
	// 「停止生成」层先吃掉（Esc 停回合、下拉还开着）。
	useDismiss({
		open,
		onClose: () => setOpen(false),
		escId: 'reasoning-levels',
		keepOpenRefs: [wrapRef],
		panelId: FLYOUT_ID,
	});

	const q = query.trim().toLowerCase();
	const options = q
		? REASONING_EFFORTS.filter(l => l.toLowerCase().includes(q))
		: REASONING_EFFORTS;

	const toggle = (level: ReasoningEffort) => {
		onChange(
			value.includes(level)
				? value.filter(l => l !== level)
				: [...REASONING_EFFORTS.filter(l => value.includes(l) || l === level)],
		);
	};

	return (
		<div ref={wrapRef} className="relative">
			<button
				type="button"
				ref={btnRef}
				aria-label={ariaLabel}
				aria-haspopup="listbox"
				aria-expanded={open}
				onClick={() => setOpen(o => !o)}
				className="xy-surface flex w-full items-center justify-between gap-2 rounded-xl border border-line bg-glass-strong px-3 py-2 text-left text-xs text-ink outline-none hover:border-accent/60 focus:border-accent"
			>
				<span
					className={cn(
						'truncate font-mono text-[11.5px]',
						value.length === 0 && 'text-mute',
					)}
				>
					{value.length > 0 ? value.join(', ') : placeholder}
				</span>
				<ChevronDown
					className={cn(
						'xy-caret h-3.5 w-3.5',
						open && 'is-open',
					)}
				/>
			</button>
			{open
				? createPortal(
						<div
							id={FLYOUT_ID}
							className="xy-menu-flyout fixed z-[1000] flex w-min flex-col overflow-hidden rounded-xl"
							style={panelStyle ?? undefined}
						>
							<div className="px-2 pt-2">
								<label className="flex h-8 items-center gap-2 rounded-lg bg-ink/[0.06] px-2.5">
									<Search className="h-3.5 w-3.5 shrink-0 text-mute" />
									<input
										value={query}
										onChange={e => setQuery(e.target.value)}
										placeholder="搜索思考等级..."
										className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none placeholder:text-mute"
									/>
								</label>
							</div>
							<div
								role="listbox"
								aria-multiselectable="true"
								className="max-h-[13.5rem] min-h-[8rem] overflow-y-auto px-1.5 py-1.5"
							>
								{options.length === 0 ? (
									<p className="px-2 py-3 text-[12px] text-mute">无匹配等级</p>
								) : (
									options.map(level => {
										const on = value.includes(level);
										return (
											<button
												key={level}
												type="button"
												role="option"
												aria-selected={on}
												onClick={() => toggle(level)}
												className={cn(
													'xy-menu-row flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px]',
													on && 'is-active',
												)}
											>
												<span className="w-4 shrink-0">
													{on ? (
														<Check
															className="h-3.5 w-3.5 text-accent"
															strokeWidth={2.4}
														/>
													) : null}
												</span>
												<span className="font-mono text-ink">{level}</span>
											</button>
										);
									})
								)}
							</div>
						</div>,
						document.body,
					)
				: null}
		</div>
	);
}
