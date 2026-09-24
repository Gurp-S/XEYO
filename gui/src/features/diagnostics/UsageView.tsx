/**
 * UsageView.tsx — 「用量」视图：按请求与重试显示 hit/miss/output 与费用（设计 §9 / §9.1）。
 *
 * 铁律：缺 usage 的尝试显示「费用未知」，绝不显示 ¥0；措辞固定为「按 usage 估算」，
 * 未拿到真实账单前不出现「实付」。三分类分列，不相加成"总消耗"。
 */
import {useMemo} from 'react';
import type {DiagRunDetail} from '@/lib/api/diagnostics';
import {
	COST_BASIS_LABEL,
	DASH,
	buildAttemptUsage,
	estimatedTotalLabel,
	fmtClock,
	fmtCostCny,
	fmtInt,
} from './model';
import {Badge, KeyValue, Notice, Section} from './ui';
import {cn} from '@/lib/utils';

export function UsageView({detail}: {detail: DiagRunDetail}) {
	const summary = detail.usage_summary;
	const rows = useMemo(() => buildAttemptUsage(detail), [detail]);
	const unknownKeys = summary?.unknown_cost_keys ?? [];

	return (
		<div className="xy-dig-col">
			<Section title="本轮用量汇总" hint={COST_BASIS_LABEL}>
				<div className="xy-dig-cost">
					<span className="xy-dig-cost-total tabular-nums">{estimatedTotalLabel(summary)}</span>
					<span className="xy-dig-cost-basis">
						{summary?.cost_basis ? `依据：${summary.cost_basis}` : '依据：未取回'}
					</span>
				</div>
				<KeyValue
					rows={[
						{k: '已结束的尝试', v: fmtInt(summary?.finished_attempts ?? null)},
						{k: '其中有用量账', v: fmtInt(summary?.priced_attempts ?? null)},
						{
							k: '费用未知的尝试',
							v:
								summary && summary.unknown_cost_attempts > 0 ? (
									<Badge tone="warn">{fmtInt(summary.unknown_cost_attempts)}</Badge>
								) : (
									fmtInt(summary?.unknown_cost_attempts ?? null)
								),
						},
						{k: '用量来源', v: summary?.cost_sources.join('、')},
						{k: '未关联到请求的用量行', v: fmtInt(summary?.unlinked_usage_rows ?? null)},
						{k: '说明', v: summary?.statement},
					]}
				/>
				{!summary ? (
					<Notice tone="warn">
						未取回用量汇总（报告未生成或来源不可读）。此处不推算任何费用。
					</Notice>
				) : null}
				{unknownKeys.length ? (
					<Notice tone="info">
						费用未知的尝试：{unknownKeys.join('、')}
						{summary && summary.unknown_cost_attempts > unknownKeys.length
							? `（另有 ${summary.unknown_cost_attempts - unknownKeys.length} 条未列出）`
							: ''}
					</Notice>
				) : null}
			</Section>

			<Section title="逐次尝试" hint="每次 (model_request_id, attempt) 一行；重试不合并">
				{rows.length === 0 ? (
					<Notice tone="info">本轮没有模型尝试记录（无记录不等于没发生）。</Notice>
				) : (
					<table className="xy-dig-table">
						<thead>
							<tr>
								<th>请求 / 尝试</th>
								<th>模型</th>
								<th>状态</th>
								<th>时间</th>
								<th className="is-num">输入·命中</th>
								<th className="is-num">输入·未命中</th>
								<th className="is-num">输出</th>
								<th className="is-num">费用</th>
							</tr>
						</thead>
						<tbody>
							{rows.map(r => (
								<tr key={r.key} className={cn(!r.hasUsage && 'is-unknown')}>
									<td className="font-mono">
										{r.requestId || DASH}
										<span className="xy-dig-attempt">
											#{r.attempt == null ? '?' : r.attempt}
										</span>
									</td>
									<td>{r.model || DASH}</td>
									<td>
										{r.failed ? (
											<Badge tone="fail">未产出正常结果</Badge>
										) : r.finished ? (
											<Badge tone="ok">已结束</Badge>
										) : (
											<Badge tone="active">未见结束记录</Badge>
										)}
									</td>
									<td className="tabular-nums">{fmtClock(r.ts)}</td>
									<td className="is-num tabular-nums">{fmtInt(r.inputHit)}</td>
									<td className="is-num tabular-nums">{fmtInt(r.inputMiss)}</td>
									<td className="is-num tabular-nums">{fmtInt(r.output)}</td>
									<td className="is-num tabular-nums">
										{r.hasUsage ? fmtCostCny(r.costCny) : '费用未知'}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				)}
				<p className="xy-dig-sub">
					命中 / 未命中 / 输出三列分列显示，不相加成「总消耗」；费用列为「—」即该尝试无用量账，
					按未知计费处理而非 0 元。
				</p>
			</Section>

			<Section title="用量原始行" hint="账本定位可复制">
				{detail.usage.length === 0 ? (
					<Notice tone="info">本会话在用量账本里没有匹配行。</Notice>
				) : (
					<table className="xy-dig-table">
						<thead>
							<tr>
								<th>attempt_key</th>
								<th>厂商 / 模型</th>
								<th className="is-num">命中</th>
								<th className="is-num">未命中</th>
								<th className="is-num">输出</th>
								<th className="is-num">费用</th>
								<th>计价来源</th>
							</tr>
						</thead>
						<tbody>
							{detail.usage.map((u, i) => (
								<tr key={`${u.attempt_key}-${i}`}>
									<td className="font-mono">{u.attempt_key || DASH}</td>
									<td>
										{u.vendor || u.provider || DASH} / {u.model || DASH}
									</td>
									<td className="is-num tabular-nums">{fmtInt(u.cache_hit)}</td>
									<td className="is-num tabular-nums">{fmtInt(u.cache_miss)}</td>
									<td className="is-num tabular-nums">{fmtInt(u.output)}</td>
									<td className="is-num tabular-nums">{fmtCostCny(u.cost_cny)}</td>
									<td>{u.cost_source || DASH}</td>
								</tr>
							))}
						</tbody>
					</table>
				)}
			</Section>
		</div>
	);
}
