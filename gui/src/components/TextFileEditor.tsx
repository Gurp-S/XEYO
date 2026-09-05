import {useCallback, useEffect, useMemo, useRef} from 'react';
import {useHoverScroll} from '@/hooks/useHoverScroll';
import {cn} from '@/lib/utils';

type Props = {
	value: string;
	onChange: (next: string) => void;
	onSave?: () => void;
	disabled?: boolean;
	className?: string;
	'aria-label'?: string;
};

export function TextFileEditor({
	value,
	onChange,
	onSave,
	disabled,
	className,
	'aria-label': ariaLabel = '文件编辑器',
}: Props) {
	const hover = useHoverScroll();
	const taRef = useRef<HTMLTextAreaElement | null>(null);
	const gutterRef = useRef<HTMLPreElement | null>(null);
	const lines = value.length === 0 ? 1 : value.split('\n').length;
	const nums = useMemo(() => {
		let out = '1';
		for (let i = 2; i <= lines; i += 1) {
			out += `\n${i}`;
		}
		return out;
	}, [lines]);

	const setTaRef = useCallback(
		(el: HTMLTextAreaElement | null) => {
			taRef.current = el;
			hover.scrollerRef(el);
		},
		[hover.scrollerRef],
	);

	const syncGutter = useCallback(() => {
		const ta = taRef.current;
		const gutter = gutterRef.current;
		if (ta && gutter) {
			gutter.scrollTop = ta.scrollTop;
		}
	}, []);

	useEffect(() => {
		syncGutter();
	}, [lines, syncGutter]);

	return (
		<div
			className={cn('flex min-h-0 min-w-0 flex-1 overflow-hidden', className)}
			onMouseEnter={hover.onMouseEnter}
			onMouseLeave={hover.onMouseLeave}
		>
			<pre
				ref={gutterRef}
				aria-hidden
				className="xy-file-gutter m-0 min-h-0 shrink-0 overflow-hidden py-2.5 text-right font-mono text-[12px] leading-5 text-mute/70 select-none"
				style={{width: `${Math.max(2, String(lines).length)}ch`}}
			>
				{nums}
			</pre>
			<textarea
				ref={setTaRef}
				value={value}
				disabled={disabled}
				spellCheck={false}
				wrap="off"
				aria-label={ariaLabel}
				onChange={e => onChange(e.target.value)}
				onScroll={syncGutter}
				onKeyDown={e => {
					if (e.key === 'Tab') {
						e.preventDefault();
						const ta = e.currentTarget;
						const start = ta.selectionStart;
						const end = ta.selectionEnd;
						const next = `${value.slice(0, start)}\t${value.slice(end)}`;
						onChange(next);
						requestAnimationFrame(() => {
							ta.selectionStart = start + 1;
							ta.selectionEnd = start + 1;
						});
						return;
					}
					if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
						e.preventDefault();
						onSave?.();
					}
				}}
				className="xy-hover-scroll xy-file-editor min-h-0 min-w-0 flex-1 resize-none border-0 bg-transparent py-2.5 pr-3 font-mono text-[12.5px] leading-5 text-ink outline-none"
			/>
		</div>
	);
}
