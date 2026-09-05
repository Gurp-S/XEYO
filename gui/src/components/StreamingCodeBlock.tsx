import {memo, useMemo} from 'react';
import {cn} from '@/lib/utils';
import {LiveFadeText} from './LiveFadeText';

type Props = {
	language?: string;
	value: string;
};

/**
 * 流式专用代码块：已完成行只追加，当前行 LiveFadeText；
 * 不做 Prism、不用 break-all。
 */
export const StreamingCodeBlock = memo(function StreamingCodeBlock({
	language = 'text',
	value,
}: Props) {
	const langLabel = (language || 'text').trim() || 'text';
	const {committed, live, lineCount} = useMemo(() => {
		const endsWithNl = value.endsWith('\n');
		const parts = value.split('\n');
		if (endsWithNl) {
			const committedLines = parts.slice(0, -1);
			return {
				committed: committedLines,
				live: '',
				lineCount: Math.max(1, committedLines.length + 1),
			};
		}
		if (parts.length === 1) {
			return {
				committed: [] as string[],
				live: parts[0] ?? '',
				lineCount: 1,
			};
		}
		return {
			committed: parts.slice(0, -1),
			live: parts[parts.length - 1] ?? '',
			lineCount: parts.length,
		};
	}, [value]);

	return (
		<div className="xy-md-surface xy-code-surface xy-stream-code my-2.5 overflow-hidden rounded-xl border">
			<div className="flex items-center justify-between gap-2 border-b border-rule-strong px-3 py-1.5 text-xs text-mute">
				<span className="inline-flex min-w-0 items-center gap-1.5">
					<span className="rounded-md bg-glass-strong px-1.5 py-0.5 font-medium uppercase tracking-wide text-ink-soft ring-1 ring-rule">
						{langLabel}
					</span>
					<span className="shrink-0 text-mute/80">{lineCount} 行</span>
				</span>
			</div>
			<pre
				className={cn(
					'xy-stream-code-pre m-0 overflow-x-auto px-4 py-3 font-mono text-[13px] leading-5 text-ink',
				)}
			>
				{committed.map((line, index) => (
					<div key={index} className="xy-code-line whitespace-pre">
						{line.length > 0 ? line : '\u00a0'}
					</div>
				))}
				<div className="xy-code-line whitespace-pre">
					{live.length > 0 ? (
						<LiveFadeText text={live} />
					) : (
						'\u00a0'
					)}
				</div>
			</pre>
		</div>
	);
});
