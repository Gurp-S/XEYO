import {ChevronDown, ChevronRight} from 'lucide-react';
import {memo, useEffect, useState} from 'react';
import {cn} from '@/lib/utils';

type Props = {
	text: string;
	active?: boolean;
	className?: string;
};

/** 占位 shimmer 不应与 Activity 里的 Thought 步骤重复展示。 */
export function shouldShowThinkingLine(text: string | undefined): boolean {
	const trimmed = (text ?? '').trim();
	if (!trimmed) {
		return false;
	}
	const lower = trimmed.toLowerCase();
	return lower !== 'thinking…' && lower !== 'thinking...' && lower !== 'working…';
}

/** 模型 reasoning 流：有实质内容时用可折叠 Thinking 区。 */
function ThinkingLineInner({text, active = true, className}: Props) {
	const [open, setOpen] = useState(active);
	const trimmed = text.trim();
	if (!shouldShowThinkingLine(trimmed)) {
		return null;
	}
	useEffect(() => {
		if (active) {
			setOpen(true);
		}
	}, [active, trimmed]);

	return (
		<div className={cn('select-none', className)}>
			<button
				type="button"
				onClick={() => setOpen(v => !v)}
				className="group inline-flex max-w-full items-center gap-1 rounded py-0.5 text-left text-[13px] leading-snug text-mute hover:text-ink-soft"
				aria-expanded={open}
			>
				<span className={cn('shrink-0', active ? 'xy-thinking' : 'text-ink-soft')}>
					Thinking
				</span>
				{open ? (
					<ChevronDown className="size-3.5 shrink-0 opacity-70" />
				) : (
					<ChevronRight className="size-3.5 shrink-0 opacity-70" />
				)}
			</button>
			{open ? (
				<div
					className={cn(
						'mt-1 border-l border-line/40 pl-3 text-[13px] leading-relaxed whitespace-pre-wrap text-mute',
						active && 'xy-thinking',
					)}
				>
					{trimmed}
				</div>
			) : null}
		</div>
	);
}

export const ThinkingLine = memo(ThinkingLineInner);
