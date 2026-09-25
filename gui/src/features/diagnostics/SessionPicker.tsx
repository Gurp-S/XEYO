/**
 * SessionPicker.tsx — 诊断页的会话选择器（替代原生 `<select>`）。
 *
 * 原生弹层的问题不是"不够好看"，而是三条具体的可用性缺陷：
 * 1. 长会话标题被系统弹层**硬截断**——没有省略号也没有 tooltip，用户无法确认
 *    两条都以「帮我测试出WSC…」开头的会话到底是不是同一个；
 * 2. 占位符「选择会话」被当成列表里的一条**可选项**（`<option value="">`），
 *    选中它等于把会话清空，而这不是任何一种"选择"；
 * 3. 弹层走操作系统配色，与玻璃层脱节（浅色下是白底 + 灰选中带）。
 *
 * 这里改成自绘 listbox：当前项有勾选标记、标题截断带省略号且 `title` 给全文、
 * 键盘可走（↑↓ / Home / End / Enter / Esc），沿用仓库里已有的 flyout 模式
 * （portal 定位，避免被设置弹层的滚动容器裁剪）。
 */
import {Check, ChevronDown} from 'lucide-react';
import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {cn} from '@/lib/utils';

const LIST_ID = 'xeyo-dig-session-listbox';
const FLYOUT_ID = 'xeyo-dig-session-flyout';
/** 弹层估算高度：用于"下方放不下就朝上翻"的判断。 */
const FLYOUT_H = 336;

export function SessionPicker({
	sessions,
	value,
	onPick,
	placeholder = '选择会话',
}: {
	sessions: Array<{id: string; label: string}>;
	value: string;
	onPick: (id: string) => void;
	placeholder?: string;
}) {
	const [open, setOpen] = useState(false);
	// 高亮项：焦点始终留在触发器上（select-only combobox 口径），
	// 所以用 aria-activedescendant 指向列表里的行，而不是把焦点搬进列表。
	const [active, setActive] = useState(0);
	const wrapRef = useRef<HTMLDivElement>(null);
	const btnRef = useRef<HTMLButtonElement>(null);
	const [pos, setPos] = useState({top: 0, left: 0, width: 0});

	const selected = sessions.findIndex(s => s.id === value);
	const current = value ? sessions[selected] : undefined;

	useLayoutEffect(() => {
		if (!open) return;
		const update = () => {
			const r = btnRef.current?.getBoundingClientRect();
			if (!r) return;
			const width = Math.max(r.width, 22 * 16);
			const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
			const below = r.bottom + FLYOUT_H < window.innerHeight || r.top < FLYOUT_H;
			setPos({top: below ? r.bottom + 6 : Math.max(8, r.top - FLYOUT_H - 6), left, width});
		};
		update();
		setActive(Math.max(0, sessions.findIndex(s => s.id === value)));
		window.addEventListener('resize', update);
		window.addEventListener('scroll', update, true);
		return () => {
			window.removeEventListener('resize', update);
			window.removeEventListener('scroll', update, true);
		};
	}, [open, sessions, value]);

	useEffect(() => {
		if (!open) return;
		const onDown = (e: MouseEvent) => {
			const t = e.target as Node;
			if (!wrapRef.current?.contains(t) && !document.getElementById(FLYOUT_ID)?.contains(t)) {
				setOpen(false);
			}
		};
		window.addEventListener('mousedown', onDown);
		return () => window.removeEventListener('mousedown', onDown);
	}, [open]);

	// 键盘把高亮项推到可视区外时，要把它滚进来：列表封顶 21rem，会话几十条时
	// 只有 aria-activedescendant 的话，看得见的人不知道自己在哪一行，读屏的人
	// 看得见行号却不知道屏幕上有没有这一行。
	useEffect(() => {
		if (!open) {
			return;
		}
		document
			.getElementById(`${LIST_ID}-${active}`)
			?.scrollIntoView({block: 'nearest'});
	}, [open, active]);

	const pick = (id: string) => {
		setOpen(false);
		if (id !== value) onPick(id);
		btnRef.current?.focus();
	};

	const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
		if (e.key === 'Escape') {
			if (open) {
				e.stopPropagation();
				setOpen(false);
			}
			return;
		}
		if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
			e.preventDefault();
			setOpen(true);
			return;
		}
		if (!open) return;
		const last = sessions.length - 1;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			setActive(i => (i >= last ? 0 : i + 1));
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			setActive(i => (i <= 0 ? last : i - 1));
		} else if (e.key === 'Home') {
			e.preventDefault();
			setActive(0);
		} else if (e.key === 'End') {
			e.preventDefault();
			setActive(last);
		} else if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			const s = sessions[active];
			if (s) pick(s.id);
		} else if (e.key === 'Tab') {
			setOpen(false);
		}
	};

	return (
		<div ref={wrapRef} className="relative">
			<button
				type="button"
				ref={btnRef}
				role="combobox"
				aria-haspopup="listbox"
				aria-expanded={open}
				aria-controls={open ? LIST_ID : undefined}
				aria-activedescendant={open && sessions[active] ? `${LIST_ID}-${active}` : undefined}
				aria-label="会话"
				title={current?.label ?? placeholder}
				onClick={() => setOpen(o => !o)}
				onKeyDown={onKeyDown}
				className={cn(
					'xy-press flex h-7 max-w-[22rem] items-center gap-1.5 rounded-[var(--xy-radius-control)]',
					'border border-line bg-glass-strong px-2.5 text-left text-[11.5px] outline-none',
					'hover:border-accent/60 focus-visible:shadow-[var(--xy-ring)]',
					current ? 'text-ink' : 'text-mute',
				)}
			>
				<span className="truncate">{current?.label ?? placeholder}</span>
				<ChevronDown className={cn('xy-caret h-3 w-3', open && 'is-open')} />
			</button>
			{open
				? createPortal(
						<div
							id={FLYOUT_ID}
							className="xy-menu-flyout fixed z-[1000] flex flex-col overflow-hidden"
							style={{top: pos.top, left: pos.left, minWidth: pos.width}}
						>
							{sessions.length === 0 ? (
								<p className="px-3 py-3 text-[12px] text-mute">后端没有可选会话。</p>
							) : (
								<div
									id={LIST_ID}
									role="listbox"
									aria-label="会话"
									className="max-h-[21rem] overflow-y-auto px-1.5 py-1.5"
								>
									{sessions.map((s, i) => {
										const on = s.id === value;
										return (
											<div
												key={s.id}
												id={`${LIST_ID}-${i}`}
												role="option"
												aria-selected={on}
												title={s.label}
												onClick={() => pick(s.id)}
												className={cn(
													'flex cursor-pointer items-center gap-2 rounded-[var(--xy-radius-tight)] px-2.5 py-1.5',
													'text-[12px] text-ink-soft hover:bg-ink/[0.06]',
													i === active && 'bg-ink/[0.06] text-ink',
												)}
											>
												<Check
													className={cn(
														'size-3.5 shrink-0',
														on ? 'opacity-100 text-accent' : 'opacity-0',
													)}
													aria-hidden
												/>
												<span className="truncate">{s.label}</span>
											</div>
										);
									})}
								</div>
							)}
						</div>,
						document.body,
					)
				: null}
		</div>
	);
}
