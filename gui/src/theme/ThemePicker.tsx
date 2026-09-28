import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';
import {THEME_CATALOG, type ThemeId, type ThemeMeta} from '@/theme/catalog';

/** 微缩预览用到的实色档位：全部由该主题元数据算出，组件里不写任何字面色。 */
type Tone = 'surface' | 'accent' | 'ink' | 'soft' | 'hair';

/**
 * 微缩窗口预览的行（自上而下）：强调条 / 标题行 / 正文行 / 发丝线 / 强调短条。
 * 四条信息各占一块**实色**面积——表面色（surface，整张卡的底）、墨色重量（ink）、
 * 线条/发丝强度（soft + hair）、强调色相（accent 两处）——相邻主题的差才不会在
 * 卡尺寸下被 alpha 叠加稀释掉。
 */
const PREVIEW_ROWS: ReadonlyArray<{
  width: string;
  tone: Exclude<Tone, 'surface'>;
  /** [设置页网格, 标题栏紧凑 popover] 行高 */
  h: [string, string];
}> = [
	{width: '100%', tone: 'accent', h: ['h-[3px]', 'h-[2px]']},
	{width: '52%', tone: 'ink', h: ['h-[3px]', 'h-[2px]']},
	{width: '74%', tone: 'soft', h: ['h-[3px]', 'h-[2px]']},
	{width: '100%', tone: 'hair', h: ['h-[2px]', 'h-px']},
	{width: '30%', tone: 'accent', h: ['h-[6px]', 'h-[4px]']},
];

/**
 * 主题元数据 → 预览档位：
 * surface = 该主题纸面（= --xy-paper 真值）；ink / accent 同理；
 * soft / hair 是同一套配比（45% / 24% 墨入纸）作用在各主题自己的纸墨上，
 * 用来把「墨有多重」「线有多实」摊成看得见的面积。
 */
function toneOf(meta: ThemeMeta): Record<Tone, string> {
	const {paper, ink, accent} = meta.swatches;
	return {
		surface: paper,
		accent,
		ink,
		soft: `color-mix(in oklab, ${ink} 45%, ${paper})`,
		hair: `color-mix(in oklab, ${ink} 24%, ${paper})`,
	};
}

/** sRGB 相对亮度（WCAG 口径），只为从元数据里挑对比更强的角标前景。 */
function luminance(hex: string): number {
	const h = hex.replace('#', '');
	const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
	const ch = [0, 2, 4].map(i => {
		const v = parseInt(full.slice(i, i + 2), 16) / 255;
		return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
	});
	return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

function contrast(a: string, b: string): number {
	const la = luminance(a);
	const lb = luminance(b);
	return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * 选中角标的前景：在「纸」与「墨」里取与该主题强调色对比更高的一档。
 * 原来写死 '#fff'（浅色主题下勉强能用，深色主题下与 accent 同亮度会糊）。
 */
function checkForegroundOf(meta: ThemeMeta): string {
	const {paper, ink, accent} = meta.swatches;
	return contrast(accent, paper) >= contrast(accent, ink) ? paper : ink;
}

type Props = {
	value: ThemeId;
	onChange: (id: ThemeId) => void;
	/** 紧凑：标题栏 popover；默认：设置页网格 */
	compact?: boolean;
	className?: string;
};

/** 二十套主题色卡：微缩窗口预览（表面 + 五条内容线，含两处强调色）+ 名称，选中仅细边框。 */
export function ThemePicker({value, onChange, compact = false, className}: Props) {
	return (
		<div
			className={cn(
				'grid gap-2',
				compact ? 'grid-cols-3 w-[236px]' : 'grid-cols-3',
				className,
			)}
			role="listbox"
			aria-label="主题"
		>
			{THEME_CATALOG.map(meta => {
				const active = value === meta.id;
				const tone = toneOf(meta);
				return (
					<button
						key={meta.id}
						type="button"
						role="option"
						aria-selected={active}
						title={meta.label}
						aria-label={meta.label}
						onClick={() => onChange(meta.id)}
						className={cn(
							'xy-press group relative flex flex-col overflow-hidden rounded-xl border text-left transition-colors',
							compact ? 'p-1.5' : 'p-2',
							active
								? 'border-accent/60 ring-1 ring-accent/30'
								: 'border-line/70 hover:border-line',
						)}
						style={{background: tone.surface}}
					>
						<span
							className={cn(
								'flex w-full flex-col justify-center gap-1 overflow-hidden rounded-md border',
								compact ? 'h-9 px-1.5' : 'h-12 px-2',
							)}
							style={{background: tone.surface, borderColor: tone.hair}}
						>
							{PREVIEW_ROWS.map(row => (
								<span
									key={`${row.tone}-${row.width}`}
									className={cn(
										'rounded-full',
										compact ? row.h[1] : row.h[0],
									)}
									style={{width: row.width, background: tone[row.tone]}}
								/>
							))}
						</span>
						<span
							className={cn(
								'mt-1.5 truncate font-medium',
								compact ? 'text-[10px]' : 'text-[11px]',
							)}
							style={{color: tone.ink}}
						>
							{meta.label}
						</span>
						{active ? (
							<span
								className="absolute right-1 top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full"
								style={{
									background: tone.accent,
									color: checkForegroundOf(meta),
								}}
							>
								<Check className="h-2.5 w-2.5" strokeWidth={3} />
							</span>
						) : null}
					</button>
				);
			})}
		</div>
	);
}
