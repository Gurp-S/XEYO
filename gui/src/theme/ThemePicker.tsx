import {Check} from 'lucide-react';
import {cn} from '@/lib/utils';
import {THEME_CATALOG, type ThemeId} from '@/theme/catalog';

type Props = {
	value: ThemeId;
	onChange: (id: ThemeId) => void;
	/** 紧凑：标题栏 popover；默认：设置页网格 */
	compact?: boolean;
	className?: string;
};

/** 十套主题色卡：纸面底 + 强调色条 + 名称，选中仅细边框。 */
export function ThemePicker({value, onChange, compact = false, className}: Props) {
	return (
		<div
			className={cn(
				'grid gap-2',
				compact ? 'grid-cols-5 w-[320px]' : 'grid-cols-5',
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
								'block w-full rounded-md',
								compact ? 'h-5' : 'h-7',
							)}
							style={{
								background: `linear-gradient(90deg, ${meta.swatches.ink} 0%, ${meta.swatches.ink} 28%, ${meta.swatches.accent} 28%, ${meta.swatches.accent} 100%)`,
								opacity: 0.85,
							}}
						/>
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
