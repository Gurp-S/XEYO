import {memo, useMemo, useRef, type ReactNode} from 'react';
import {
	parseStreamTable,
	type StreamTableAlign,
	type StreamTablePending,
} from '@/lib/streamMarkdown';
import {LiveFadeText} from './LiveFadeText';

function alignClass(align: StreamTableAlign | undefined): string | undefined {
	if (align === 'center') {
		return 'text-center';
	}
	if (align === 'right') {
		return 'text-right';
	}
	if (align === 'left') {
		return 'text-left';
	}
	return undefined;
}

const StableRow = memo(function StableRow({
	cells,
	aligns,
}: {
	cells: string[];
	aligns: StreamTableAlign[];
}) {
	return (
		<tr>
			{cells.map((cell, i) => (
				<td
					key={i}
					className={`border-b border-line/35 px-2.5 py-1.5 text-ink-soft first:pl-3 last:pr-3 last:border-b-0 ${alignClass(aligns[i]) ?? ''}`}
				>
					{cell || '\u00a0'}
				</td>
			))}
		</tr>
	);
});

function TableShell({
	headers,
	aligns,
	headerGrowing,
	body,
}: {
	headers: string[];
	aligns?: StreamTableAlign[];
	headerGrowing?: boolean;
	body?: ReactNode;
}) {
	const colCount = Math.max(1, headers.length);
	const widths = useRef<string[] | null>(null);
	if (!widths.current || widths.current.length !== colCount) {
		const pct = `${(100 / colCount).toFixed(4)}%`;
		widths.current = Array.from({length: colCount}, () => pct);
	}
	return (
		<div className="xy-md-surface xy-stream-table my-2.5 overflow-x-auto rounded-xl border border-line/55 px-0 py-0">
			<table className="w-full border-collapse text-left text-[13px]">
				<colgroup>
					{widths.current.map((w, i) => (
						<col key={i} style={{width: w}} />
					))}
				</colgroup>
				<thead>
					<tr>
						{headers.map((h, i) => {
							const isLive =
								Boolean(headerGrowing) && i === headers.length - 1;
							return (
								<th
									key={i}
									className={`border-b border-line/50 bg-glass-soft/50 px-2.5 py-1.5 font-medium text-ink first:pl-3 last:pr-3 ${alignClass(aligns?.[i]) ?? ''}`}
								>
									{isLive && h ? (
										<LiveFadeText text={h} />
									) : (
										h || '\u00a0'
									)}
								</th>
							);
						})}
					</tr>
				</thead>
				{body}
			</table>
		</div>
	);
}

/**
 * Pending table (header ready / delimiter still streaming):
 * cell preview only — never paint `|` or `---`.
 */
export const StreamingTablePending = memo(function StreamingTablePending({
	pending,
}: {
	pending: StreamTablePending;
}) {
	const headers =
		pending.headers.length > 0 ? pending.headers : ['\u00a0'];
	return (
		<div className="xy-stream-pending-table">
			<TableShell
				headers={headers}
				headerGrowing={pending.growingHeader}
				body={
					<tbody>
						<tr aria-hidden>
							{headers.map((_, i) => (
								<td
									key={i}
									className="border-b border-line/20 px-2.5 py-1.5 text-mute first:pl-3 last:pr-3"
								>
									<span className="inline-block h-2 w-10 rounded bg-line/30" />
								</td>
							))}
						</tr>
					</tbody>
				}
			/>
		</div>
	);
});

/**
 * Established streaming table: freeze header/widths; fade last cell only.
 */
export const StreamingTable = memo(function StreamingTable({
	source,
}: {
	source: string;
}) {
	const model = useMemo(() => parseStreamTable(source), [source]);

	if (!model) {
		// Should be rare; never dump raw pipes — show a minimal placeholder.
		return (
			<div className="xy-stream-pending-table my-2.5 rounded-xl border border-line/55 px-3 py-2 text-[13px] text-mute">
				…
			</div>
		);
	}

	const live = model.liveRow;

	return (
		<TableShell
			headers={model.headers}
			aligns={model.aligns}
			body={
				<tbody>
					{model.rows.map((row, ri) => (
						<StableRow key={ri} cells={row} aligns={model.aligns} />
					))}
					{live ? (
						<tr className="xy-stream-table-live">
							{live.map((cell, i) => {
								const isLiveCell = i === live.length - 1;
								return (
									<td
										key={i}
										className={`border-b border-line/35 px-2.5 py-1.5 text-ink-soft first:pl-3 last:pr-3 last:border-b-0 ${alignClass(model.aligns[i]) ?? ''}`}
									>
										{isLiveCell ? (
											cell ? (
												<LiveFadeText text={cell} />
											) : (
												'\u00a0'
											)
										) : (
											cell || '\u00a0'
										)}
									</td>
								);
							})}
						</tr>
					) : null}
				</tbody>
			}
		/>
	);
});
