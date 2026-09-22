import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';
import {THEME_CATALOG, type ThemeId} from '@/theme/catalog';

/** 微缩预览的三行内容线：标题 / 正文 / 强调色短条。 */
const PREVIEW_LINES: ReadonlyArray<{
	width: string;
	opacity?: number;
	accent?: boolean;
}> = [
	{width: '52%', opacity: 0.62},
	{width: '74%', opacity: 0.22},
	{width: '30%', accent: true},
];

type Props = {
	value: ThemeId;
	onChange: (id: ThemeId) => void;
	/** 紧凑：标题栏 popover；默认：设置页网格 */
	compact?: boolean;
	className?: string;
};

/** 六套主题色卡：微缩窗口预览（表面 + 三行内容线，末行为强调色）+ 名称，选中仅细边框。 */
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
						style={{background: meta.swatches.paper}}
					>
						<span
							className={cn(
								'flex w-full flex-col justify-center gap-1 overflow-hidden rounded-md border border-line/50',
								compact ? 'h-9 px-1.5' : 'h-12 px-2',
							)}
							style={{
								background: `color-mix(in oklab, ${meta.swatches.paper} 92%, ${meta.swatches.ink})`,
							}}
						>
							{PREVIEW_LINES.map(line => (
								<span
									key={line.width}
									className={cn(
										'rounded-full',
										compact ? 'h-[2px]' : 'h-[3px]',
									)}
									style={{
										width: line.width,
										background: line.accent
											? meta.swatches.accent
											: meta.swatches.ink,
										opacity: line.accent ? 0.9 : line.opacity,
									}}
								/>
							))}
						</span>
						<span
							className={cn(
								'mt-1.5 truncate font-medium',
								compact ? 'text-[10px]' : 'text-[11px]',
							)}
							style={{color: meta.swatches.ink}}
						>
							{meta.label}
						</span>
						{active ? (
							<span
								className="absolute right-1 top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full"
								style={{
									background: meta.swatches.accent,
									color: meta.scheme === 'dark' ? meta.swatches.paper : '#fff',
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
