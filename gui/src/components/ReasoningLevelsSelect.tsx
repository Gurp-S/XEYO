import {Check, ChevronDown, Search} from 'lucide-react';
import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {cn} from '@/lib/utils';
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
	const [pos, setPos] = useState<{top: number; left: number; width: number}>({
		top: 0,
		left: 0,
		width: 0,
	});

	useLayoutEffect(() => {
		if (!open) {
			return;
		}
		const update = () => {
			const r = btnRef.current?.getBoundingClientRect();
			if (!r) {
				return;
			}
			const width = Math.max(r.width, 14 * 16);
			const left = Math.min(
				r.left,
				window.innerWidth - width - 8,
			);
			// 下方放不下则翻转到触发器上方。
			const estH = 320;
			const below =
				r.bottom + estH < window.innerHeight || r.top < estH;
			setPos({
				top: below ? r.bottom + 6 : Math.max(8, r.top - estH - 6),
				left: Math.max(8, left),
				width,
			});
		};
		update();
		window.addEventListener('resize', update);
		window.addEventListener('scroll', update, true);
		return () => {
			window.removeEventListener('resize', update);
			window.removeEventListener('scroll', update, true);
		};
	}, [open]);

	useEffect(() => {
		if (!open) {
			return;
		}
		const onDown = (e: MouseEvent) => {
			if (
				!wrapRef.current?.contains(e.target as Node) &&
				!document
					.getElementById('xeyo-reasoning-levels-flyout')
					?.contains(e.target as Node)
			) {
				setOpen(false);
			}
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				setOpen(false);
			}
		};
		window.addEventListener('mousedown', onDown);
		window.addEventListener('keydown', onKey);
		return () => {
			window.removeEventListener('mousedown', onDown);
			window.removeEventListener('keydown', onKey);
		};
	}, [open]);

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
						'h-3.5 w-3.5 shrink-0 opacity-50 transition-transform',
						open && 'rotate-180 opacity-80',
					)}
				/>
			</button>
			{open
				? createPortal(
						<div
							id="xeyo-reasoning-levels-flyout"
							className="xy-menu-flyout fixed z-[1000] flex w-min flex-col overflow-hidden rounded-xl"
							style={{
								top: pos.top,
								left: pos.left,
								minWidth: pos.width,
							}}
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
