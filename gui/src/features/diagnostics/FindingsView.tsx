/**
 * FindingsView.tsx — 「问题」视图（设计 §3.1 / §6）。
 *
 * 铁律：
 * - 归因块永远在最前：首个已确认异常边界 / 最后一个已确认正常边界 / statement。
 * - 没有已确认异常时显示免责句，不渲染成绿色通过。
 * - attributed=false 显示「无法归因」。
 * - 不出现概率、不出现加权总分（后端也没有这些字段，前端更不合成）。
 */
import {useState} from 'react';
import {ChevronRight} from 'lucide-react';
import type {DiagFinding, DiagRunDetail} from '@/lib/api/diagnostics';
import {
	DASH,
	FINDING_STATUS_LABEL,
	NO_CONFIRMED_FAULT_TEXT,
	NOT_ATTRIBUTED_TEXT,
	attributionLines,
	boundaryLabelOf,
	PARTY_LABEL,
	PARTY_TONE,
	SHOWN_LABEL,
	findingStatusOf,
	groupFindingsByStatus,
	hasConfirmedFault,
} from './model';
import {Badge, EvidenceList, KeyValue, Notice, Section} from './ui';
import {cn} from '@/lib/utils';

const STATUS_TONE: Record<string, 'confirmed' | 'suspect' | 'unknown'> = {
	confirmed_fault: 'confirmed',
	suspected_cause: 'suspect',
	unknown: 'unknown',
};

function FindingCard({f, boundaryLabel}: {f: DiagFinding; boundaryLabel: string}) {
	const [open, setOpen] = useState(false);
	const status = findingStatusOf(f);
	return (
		<li className={cn('xy-dig-finding', `is-${status}`)}>
			<button
				type="button"
				className="xy-dig-finding-head"
				aria-expanded={open}
				onClick={() => setOpen(v => !v)}
			>
				<ChevronRight
					className={cn('xy-dig-chevron size-3.5 shrink-0', open && 'is-open')}
					aria-hidden
				/>
				<Badge tone={STATUS_TONE[status]}>{FINDING_STATUS_LABEL[status]}</Badge>
				<span className="xy-dig-finding-what">
					<span className="xy-dig-finding-phenomenon">{f.phenomenon || DASH}</span>
					<span className="xy-dig-finding-meta">
						边界 {boundaryLabel}　功能归属 {f.component || DASH}　规则{' '}
						<span className="font-mono">{f.rule_id || DASH}</span>
						{f.rule_version != null ? ` v${f.rule_version}` : ''}
					</span>
				</span>
			</button>
			{open ? (
				<div className="xy-dig-finding-body">
					<KeyValue
						rows={[
							{k: '影响', v: f.impact},
							{k: '允许下的结论', v: f.allowed_conclusion},
							{k: '本规则看不到的范围', v: f.coverage_gap},
						]}
					/>
					<p className="xy-dig-sub">原始记录（点击复制定位）</p>
					<EvidenceList items={f.evidence} />
				</div>
			) : null}
		</li>
	);
}

function Group({
	status,
	items,
	boundaryLabel,
}: {
	status: 'confirmed_fault' | 'suspected_cause' | 'unknown';
	items: DiagFinding[];
	boundaryLabel: (name: string) => string;
}) {
	if (!items.length) return null;
	return (
		<div className="xy-dig-group">
			<h4 className="xy-dig-group-title">
				<Badge tone={STATUS_TONE[status]}>{FINDING_STATUS_LABEL[status]}</Badge>
				<span className="xy-dig-count tabular-nums">{items.length} 条</span>
			</h4>
			<ul className="xy-dig-findings">
				{items.map((f, i) => (
					<FindingCard
						key={`${f.rule_id}|${f.boundary}|${i}`}
						f={f}
						boundaryLabel={boundaryLabel(f.boundary)}
					/>
				))}
			</ul>
		</div>
	);
}

export function FindingsView({detail}: {detail: DiagRunDetail}) {
	const groups = groupFindingsByStatus(detail.findings);
	const boundaryLabel = (name: string) => boundaryLabelOf(detail, name);
	const attributed = detail.attribution?.attributed === true;
	const confirmed = hasConfirmedFault(detail.findings);
	return (
		<div className="xy-dig-col">
			{detail.fault ? (
				<Section title="责任划分" hint="判模型的错需要送达证据；没发现引擎异常不等于模型有错">
					<div className="xy-dig-fault">
						<div className="xy-dig-fault-head">
							<Badge tone={PARTY_TONE[detail.fault.responsibility] ?? 'unknown'}>
								{detail.fault.responsibility_label ||
									PARTY_LABEL[detail.fault.responsibility] ||
									DASH}
							</Badge>
							<Badge tone="neutral">任务：{detail.fault.task_outcome_label || DASH}</Badge>
							<Badge tone="neutral">
								约束：{SHOWN_LABEL[detail.fault.shown_to_model] || detail.fault.shown_to_model || DASH}
							</Badge>
						</div>
						{detail.fault.causes.length ? (
							<ul className="xy-dig-causes">
								{detail.fault.causes.map(c => (
									<li key={`${c.code}-${c.detail_kind ?? ''}`}>
										<Badge tone={PARTY_TONE[c.party] ?? 'unknown'}>
											{PARTY_LABEL[c.party] ?? c.party}
										</Badge>
										<span className="xy-dig-cause-label">
											{c.label}
											{c.detail_kind ? <span className="mono"> · {c.detail_kind}</span> : null}
										</span>
										<span className="xy-dig-cause-mono mono">{c.code}</span>
										<span className="xy-dig-cause-limits">
											能证明：{c.proves}；不能证明：{c.does_not_prove}
										</span>
									</li>
								))}
							</ul>
						) : null}
						<p className="xy-dig-fault-why">{detail.fault.why}</p>
						{detail.fault.obligation.excerpt ? (
							<KeyValue
								rows={[
									{
										k: '约束来源',
										v:
											detail.fault.obligation.source === 'pin'
												? '事后固定的预期（不能据此判上下文丢了它）'
												: detail.fault.obligation.source === 'turn_user_message'
													? '本轮用户原话（当场在场）'
													: (detail.fault.obligation.source || DASH),
									},
									{k: '约束内容', v: detail.fault.obligation.excerpt},
									{k: '送达判据', v: detail.fault.shown_to_model_note},
								]}
							/>
						) : null}
						{detail.fault.chain.length ? (
							<ul className="xy-dig-chain">
								{detail.fault.chain.map(s => (
									<li key={`${s.order}-${s.boundary}`}>
										<Badge tone={PARTY_TONE[s.party] ?? 'unknown'}>{s.party_label || s.party}</Badge>
										<span className="xy-dig-chain-fact">{s.fact}</span>
										<EvidenceList items={s.evidence} />
									</li>
								))}
							</ul>
						) : null}
						{detail.fault.missing_evidence.length ? (
							<>
								<p className="xy-dig-subtitle">改判还缺的证据</p>
								<ul className="xy-dig-facts">
									{detail.fault.missing_evidence.map((x, i) => (
										<li key={i}>{x}</li>
									))}
								</ul>
							</>
						) : null}
						{detail.fault.not_claimed.length ? (
							<p className="xy-dig-foot">本报告不宣称：{detail.fault.not_claimed.join(' · ')}</p>
						) : null}
					</div>
				</Section>
			) : null}

			<Section title="归因" hint="定位到边界，不宣称是任务失败的全部原因">
				<div className="xy-dig-attr">
					{attributionLines(detail).map((line, i) => (
						<p key={i} className={cn('xy-dig-attr-line', i === 0 && 'is-lead')}>
							{line}
						</p>
					))}
					{!attributed ? <Badge tone="unknown">{NOT_ATTRIBUTED_TEXT}</Badge> : null}
					{/* 归因块没取回时三档计数一个都没有：0 会被读成"都已确认不是 0"。 */}
					{detail.attribution ? (
						<div className="xy-dig-attr-counts tabular-nums">
							<span>已确认 {detail.attribution.confirmed_count}</span>
							<span>疑似 {detail.attribution.suspected_count}</span>
							<span>未定 {detail.attribution.unknown_count}</span>
						</div>
					) : null}
				</div>
				{!confirmed ? <Notice tone="info">{NO_CONFIRMED_FAULT_TEXT}</Notice> : null}
			</Section>

			{detail.findings.length === 0 ? (
				<Notice tone="info">
					规则集未产生结论 —— 这不代表没有异常，只代表这些规则没看到。
				</Notice>
			) : null}

			<Group status="confirmed_fault" items={groups.confirmed_fault} boundaryLabel={boundaryLabel} />
			<Group status="suspected_cause" items={groups.suspected_cause} boundaryLabel={boundaryLabel} />
			<Group status="unknown" items={groups.unknown} boundaryLabel={boundaryLabel} />

			{detail.notes.length ? (
				<Section title="采集侧说明" hint="后端原样带出，不做解释性加工">
					<ul className="xy-dig-list">
						{detail.notes.map((nt, i) => (
							<li key={i}>{nt}</li>
						))}
					</ul>
				</Section>
			) : null}
		</div>
	);
}
