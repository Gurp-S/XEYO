/**
 * StepsView.tsx — 「步骤」视图：从请求到验收的时间线（设计 §3.1 / §5.1）。
 *
 * 硬性要求：
 * - 一个逻辑调用的每次重试各自成行（绝不折叠成最后一次）；
 * - 等待授权与长任务各自有独立措辞与配色，不当成失败/卡死；
 * - 有耗时记录才显示耗时，没有就显示破折号，不推算。
 */
import {useMemo, useState} from 'react';
import {Loader2} from 'lucide-react';
import type {DiagRunDetail} from '@/lib/api/diagnostics';
import {
	DASH,
	buildTimeline,
	fmtClock,
	fmtCostCny,
	fmtDuration,
	fmtInt,
	type TimelineRow,
} from './model';
import {EvidenceList, KeyValue, Notice, Section} from './ui';
import {cn} from '@/lib/utils';

const SOURCES = [
	{key: 'all', label: '全部'},
	{key: 'model', label: '模型'},
	{key: 'tool', label: '工具'},
	{key: 'permission', label: '权限'},
	{key: 'job', label: '后台任务'},
	{key: 'event', label: '其他记录'},
] as const;

type SourceKey = (typeof SOURCES)[number]['key'];

const TONE_LABEL: Record<TimelineRow['tone'], string> = {
	neutral: '记录',
	active: '进行中',
	waiting: '等待',
	ok: '完成',
	warn: '受阻',
	fail: '失败',
};

function Row({row}: {row: TimelineRow}) {
	const [open, setOpen] = useState(false);
	return (
		<li className={cn('xy-dig-step', `is-${row.tone}`)}>
			<span className="xy-dig-step-rail" aria-hidden>
				<span className="xy-dig-step-dot" />
			</span>
			<div className="xy-dig-step-main">
				<button
					type="button"
					className="xy-dig-step-head"
					aria-expanded={open}
					onClick={() => setOpen(v => !v)}
				>
					<span className="xy-dig-step-time tabular-nums">{fmtClock(row.ts)}</span>
					<span className="xy-dig-step-tone">{TONE_LABEL[row.tone]}</span>
					<span className="xy-dig-step-title">{row.title}</span>
					{row.attemptText ? (
						<span className="xy-dig-step-attempt">{row.attemptText}</span>
					) : null}
					<span className="xy-dig-step-status">{row.statusText || DASH}</span>
					<span className="xy-dig-step-dur tabular-nums">
						{row.durationMs == null ? DASH : fmtDuration(row.durationMs)}
					</span>
					<span className="xy-dig-step-cost tabular-nums">
						{row.source === 'model' ? fmtCostCny(row.hasUsage ? row.costCny : null) : null}
					</span>
				</button>
				{open ? (
					<div className="xy-dig-step-body">
						<KeyValue
							rows={[
								{k: '事件类型', v: row.kind, mono: true},
								{k: '关联身份', v: row.subject, mono: true},
								{k: '边界', v: row.boundary},
								{k: '审计行号', v: row.lineNo == null ? DASH : `L${row.lineNo}`},
								{k: '耗时', v: row.durationMs == null ? '无耗时记录' : fmtDuration(row.durationMs)},
							]}
						/>
						<EvidenceList items={row.evidence} />
					</div>
				) : null}
			</div>
		</li>
	);
}

export function StepsView({
	detail,
	loadingMore,
	onLoadMore,
}: {
	detail: DiagRunDetail;
	loadingMore: boolean;
	onLoadMore: () => void;
}) {
	const [source, setSource] = useState<SourceKey>('all');
	const rows = useMemo(() => buildTimeline(detail), [detail]);
	const shown = source === 'all' ? rows : rows.filter(r => r.source === source);
	const attempts = detail.identity.attempt_keys.length;
	const logicalCalls = detail.model_requests.length;

	return (
		<div className="xy-dig-col">
			<Section title="链路身份" hint="沿用既有 ID，不新建主键">
				<KeyValue
					rows={[
						{
							k: '逻辑模型调用 / 实际尝试',
							v: `${logicalCalls} / ${attempts}`,
							mono: true,
						},
						{k: '工具调用', v: fmtInt(detail.tool_calls.length)},
						{k: '审批请求', v: fmtInt(detail.permissions.length)},
						{k: '审计事件（本页/总）', v: `${detail.events.length} / ${detail.event_total}`},
					]}
				/>
				{attempts > logicalCalls ? (
					<Notice tone="info">
						存在重试：每个 (model_request_id, attempt) 各自成行，未合并成最后一次。
					</Notice>
				) : null}
			</Section>

			<div className="xy-dig-filter" role="group" aria-label="步骤来源筛选">
				{SOURCES.map(s => {
					const count = s.key === 'all' ? rows.length : rows.filter(r => r.source === s.key).length;
					return (
						<button
							key={s.key}
							type="button"
							aria-pressed={source === s.key}
							onClick={() => setSource(s.key)}
							className={cn('xy-dig-chip', source === s.key && 'is-on')}
						>
							{s.label}
							<span className="tabular-nums">{count}</span>
						</button>
					);
				})}
			</div>

			{shown.length === 0 ? (
				<Notice tone="info">该来源在本轮没有记录（无记录不等于没发生，见「上下文」的覆盖情况）。</Notice>
			) : (
				<ul className="xy-dig-steps">
					{shown.map(r => (
						<Row key={r.key} row={r} />
					))}
				</ul>
			)}

			{!detail.events_complete ? (
				<button
					type="button"
					className="xy-dig-more"
					disabled={loadingMore}
					onClick={onLoadMore}
				>
					{loadingMore ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
					继续加载后续事件（游标 {detail.next_event_cursor || detail.event_offset + detail.event_limit}）
				</button>
			) : null}
		</div>
	);
}
