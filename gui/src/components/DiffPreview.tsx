import {memo, useMemo, useState} from 'react';
import {showContextMenu} from '@/components/ui/ContextMenu';
import {cn} from '@/lib/utils';
import {copyTextToClipboard} from '@/lib/workspaceOpen';
import {Copy} from 'lucide-react';

type DiffLine = {
	kind: 'meta' | 'add' | 'del' | 'ctx' | 'hunk' | 'note';
	text: string;
};

/** 软折叠阈值：淡出 + 展开控件。 */
const COLLAPSE_AFTER = 12;
/** 折叠时的硬上限（多余行位于淡出下方）。 */
const COLLAPSED_MAX = 15;

export function parseUnifiedDiff(diff: string): DiffLine[] {
	const out: DiffLine[] = [];
	for (const raw of diff.replace(/\r\n/g, '\n').split('\n')) {
		if (raw.startsWith('…')) {
			out.push({kind: 'note', text: raw});
			continue;
		}
		if (
			raw.startsWith('+++') ||
			raw.startsWith('---') ||
			raw.startsWith('diff ') ||
			raw.startsWith('index ')
		) {
			out.push({kind: 'meta', text: raw});
			continue;
		}
		if (raw.startsWith('@@')) {
			out.push({kind: 'hunk', text: raw});
			continue;
		}
		if (raw.startsWith('+')) {
			out.push({kind: 'add', text: raw});
			continue;
		}
		if (raw.startsWith('-')) {
			out.push({kind: 'del', text: raw});
			continue;
		}
		out.push({kind: 'ctx', text: raw});
	}
	return out;
}

type Props = {
	diff: string;
	className?: string;
	/** 预览栏：展开全部 diff，占满剩余高度。 */
	fill?: boolean;
};

function DiffPreviewInner({diff, className, fill = false}: Props) {
	const lines = useMemo(() => parseUnifiedDiff(diff), [diff]);
	const needsCollapse = !fill && lines.length > COLLAPSE_AFTER;
	const [expanded, setExpanded] = useState(fill);

	const visible =
		!expanded && needsCollapse
			? lines.slice(0, COLLAPSED_MAX)
			: lines;
	const hidden = lines.length - visible.length;
	const collapsed = needsCollapse && !expanded;

	return (
		<div
			title="投影视图：来自工具结果投影，非完整 transcript"
			className={cn(
				'xy-diff-preview relative rounded-lg border border-line/50 font-mono text-[11px] leading-relaxed',
				fill && 'min-h-0 flex-1 overflow-auto rounded-none border-0',
				className,
			)}
			onContextMenu={event => {
				if (!diff.trim()) {
					return;
				}
				showContextMenu(
					event,
					[
						{
							kind: 'action',
							id: 'copy-diff',
							label: '复制 Diff',
							icon: <Copy className="h-3.5 w-3.5" strokeWidth={1.9} />,
							onSelect: () => void copyTextToClipboard(diff),
						},
					],
					'Diff',
				);
			}}
		>
			<div
				className={cn(
					collapsed && 'xy-diff-preview-clamp overflow-hidden',
				)}
			>
				{visible.map((line, i) => (
					<div
						key={`${i}-${line.kind}-${line.text.slice(0, 24)}`}
						className={cn(
							'whitespace-pre-wrap break-all px-2 py-px',
							line.kind === 'add' && 'xy-diff-add',
							line.kind === 'del' && 'xy-diff-del',
							line.kind === 'hunk' && 'xy-diff-hunk',
							line.kind === 'meta' && 'xy-diff-meta',
							line.kind === 'note' && 'xy-diff-note',
							line.kind === 'ctx' && 'xy-diff-ctx',
						)}
					>
						{line.text || ' '}
					</div>
				))}
			</div>

			{collapsed ? (
				<>
					<div
						aria-hidden
						className="xy-diff-fade pointer-events-none absolute inset-x-0 bottom-0 h-14 rounded-b-lg"
					/>
					<div className="pointer-events-none absolute inset-x-0 bottom-0 flex h-14 items-center justify-center">
						<button
							type="button"
							className="pointer-events-auto rounded-full border border-line/60 bg-glass-strong px-2.5 py-1 font-sans text-[11px] leading-none text-ink-soft shadow-sm transition-colors hover:bg-glass-hover hover:text-ink"
							onClick={() => setExpanded(true)}
						>
							展开全部
							{hidden > 0 ? `（+${hidden}）` : ''}
						</button>
					</div>
				</>
			) : null}
		</div>
	);
}

export const DiffPreview = memo(DiffPreviewInner);
