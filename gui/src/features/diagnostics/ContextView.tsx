/**
 * ContextView.tsx — 「上下文」视图：边界覆盖、缺项、采集状态、事实定位链（设计 §4 / §6.2）。
 *
 * 措辞纪律：absent 只说明"该来源没有记录"，绝不说明"没有发生"；
 * 定位链任一级未记账时，后端判无法归因，前端必须把 caveat 摆在显眼处。
 */
import {useEffect, useRef, useState} from 'react';
import {Loader2} from 'lucide-react';
import {traceDiagFact, type DiagFactTrace, type DiagRunDetail} from '@/lib/api/diagnostics';
import {DASH, coverageStateLabel, factStateLabel, fmtBytes, gapReasonLabel, ledgerCountText} from './model';
import {Badge, EvidenceList, KeyValue, Notice, Section} from './ui';
import {cn} from '@/lib/utils';

const FACT_STATE_TONE: Record<string, 'ok' | 'warn' | 'fail' | 'neutral'> = {
	found: 'ok',
	absent: 'warn',
	not_recorded: 'neutral',
	not_captured: 'neutral',
	unreadable: 'fail',
};

function FactChain({trace}: {trace: DiagFactTrace}) {
	return (
		<div className="xy-dig-fact">
			<ol className="xy-dig-stages">
				{trace.stages.map((st, i) => (
					<li key={`${st.stage}-${i}`} className={cn('xy-dig-stage', `is-${st.state}`)}>
						<span className="xy-dig-stage-no tabular-nums">{i + 1}</span>
						<span className="xy-dig-stage-label">{st.label || st.stage || DASH}</span>
						<Badge tone={FACT_STATE_TONE[st.state] ?? 'neutral'}>
							{factStateLabel(st.state)}
						</Badge>
						{st.note ? <span className="xy-dig-stage-note">{st.note}</span> : null}
						{st.evidence.length ? <EvidenceList items={st.evidence} /> : null}
					</li>
				))}
			</ol>
			<Notice tone={trace.verdict === 'unknown' ? 'warn' : 'info'}>
				{trace.statement || '各级记录不足以判断这条事实的命运。'}
			</Notice>
			{trace.unprovable_stages.length ? (
				<p className="xy-dig-sub">
					不可证明的级别：{trace.unprovable_stages.join('、')}
				</p>
			) : null}
			<p className="xy-dig-caveat">注意：{trace.caveat || '字符串匹配不代表模型理解了该事实。'}</p>
		</div>
	);
}

export function ContextView({
	detail,
	sessionId,
	turnId,
	storeRoot,
}: {
	detail: DiagRunDetail;
	sessionId: string;
	turnId: string;
	storeRoot: string;
}) {
	const [needle, setNeedle] = useState('');
	const [trace, setTrace] = useState<DiagFactTrace | null>(null);
	const [busy, setBusy] = useState(false);
	const [err, setErr] = useState('');
	// 定位一次要重扫全尾窗（最长 60s）：连点两下不能让先发的慢响应盖掉后发的，
	// 也不能在组件已卸载后再写 state。
	const traceReqRef = useRef(0);
	const mountedRef = useRef(true);
	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
			traceReqRef.current += 1;
		};
	}, []);

	useEffect(() => {
		traceReqRef.current += 1;
		setBusy(false);
		setTrace(null);
		setErr('');
	}, [turnId, sessionId]);

	const run = async () => {
		const q = needle.trim();
		if (!q) {
			setErr('请输入要定位的事实（原文片段或 ID）。');
			return;
		}
		const id = traceReqRef.current + 1;
		traceReqRef.current = id;
		setBusy(true);
		setErr('');
		try {
			const t = await traceDiagFact(sessionId, turnId, q);
			if (!mountedRef.current || traceReqRef.current !== id) return;
			// 载荷自证身份：后端回的是哪一轮就对哪一轮，不符就不呈现。
			if (t.turn_id && turnId && t.turn_id !== turnId) return;
			setErr('');
			setTrace(t);
		} catch (e) {
			if (!mountedRef.current || traceReqRef.current !== id) return;
			setErr(e instanceof Error ? e.message : String(e));
			setTrace(null);
		} finally {
			if (mountedRef.current && traceReqRef.current === id) setBusy(false);
		}
	};

	const coverage = Object.entries(detail.coverage);
	// 每个账本都要先确认"这一路窗口本次到底取回没有"，没取回就不能报 0 条。
	const captureWindow = detail.windows.find(w => w.source === 'captures');
	const foldWindow = detail.windows.find(w => w.source === 'fold_events');
	const projectionWindow = detail.windows.find(w => w.source === 'working');
	const dropWindow = detail.windows.find(w => w.source === 'wire_drops');

	return (
		<div className="xy-dig-col">
			<Section title="边界覆盖" hint="有记录 = 证据能回到原始行；无记录不等于该步骤没发生">
				<ul className="xy-dig-boundaries">
					{detail.boundaries.map(bd => (
						<li key={bd.name} className={cn('xy-dig-boundary', bd.present ? 'is-present' : 'is-absent')}>
							<span className="xy-dig-boundary-label">{bd.label || bd.name}</span>
							<span className="xy-dig-boundary-count tabular-nums">
								{bd.present ? `证据 ${bd.evidence_count}` : '无记录'}
							</span>
							{bd.notes.length ? (
								<span className="xy-dig-boundary-notes">{bd.notes.join('；')}</span>
							) : null}
							{bd.present ? <EvidenceList items={bd.evidence.slice(0, 6)} /> : null}
						</li>
					))}
				</ul>
				{detail.boundaries.length === 0 ? (
					<Notice tone="info">后端未返回边界列表：无法确认本轮覆盖了哪些链路阶段。</Notice>
				) : null}
			</Section>

			<Section title="来源窗口" hint="扫描范围与截断情况">
				{coverage.length ? (
					<table className="xy-dig-table">
						<thead>
							<tr>
								<th>来源</th>
								<th>状态</th>
								<th>条数</th>
								<th>说明</th>
							</tr>
						</thead>
						<tbody>
							{coverage.map(([source, c]) => (
								<tr key={source}>
									<td className="font-mono">{source}</td>
									<td>
										<Badge tone={c.state === 'full' ? 'ok' : c.state === 'absent' ? 'neutral' : 'warn'}>
											{coverageStateLabel(c.state)}
										</Badge>
									</td>
									<td className="tabular-nums">{c.rows}</td>
									<td>{c.note || DASH}</td>
								</tr>
							))}
						</tbody>
					</table>
				) : (
					<Notice tone="info">无来源窗口记录。</Notice>
				)}
			</Section>

			<Section title="证据缺项" hint="缺什么、为什么缺；不用默认值填补">
				{detail.gaps.length ? (
					<ul className="xy-dig-list">
						{detail.gaps.map((g, i) => (
							<li key={i}>
								<span className="xy-dig-gap-boundary">{g.boundary || DASH}</span>
								<span className="xy-dig-gap-reason">{gapReasonLabel(g.reason)}</span>
								<span>{g.detail || DASH}</span>
							</li>
						))}
					</ul>
				) : (
					<Notice tone="info">本轮未记录到缺项；未记录不等于没有缺项（见上方覆盖情况）。</Notice>
				)}
			</Section>

			<Section title="本轮采集状态" hint="可复现记录只写文件，不改变模型可见内容">
				<KeyValue
					rows={[
						{
							k: '适配器最终请求体',
							v: captureWindow
								? captureWindow.complete
									? `已采集（${captureWindow.rows_matched} 条，${fmtBytes(captureWindow.bytes_read || null)}）`
									: `未采集：${captureWindow.note || '该会话未开启可复现记录'}`
								: detail.captures.length
									? `已采集 ${detail.captures.length} 条（无 captures 窗口，不声称条数完整）`
									: '未取回（本次响应没有 captures 窗口）',
						},
						{
							k: '折叠记录',
							v: ledgerCountText(foldWindow, detail.folds.length, '条', '折叠'),
						},
						{
							k: '投影 manifest',
							v: ledgerCountText(projectionWindow, detail.projections.length, '份', '投影'),
						},
						{k: '诊断目录', v: storeRoot, mono: true},
						{
							k: '丢行账本命中',
							v: dropWindow
								? detail.wire_drops.length
									? `${detail.wire_drops.length} 条交集${dropWindow.complete ? '' : '（窗口未读全，实际不少于此数）'}`
									: '无交集记录'
								: '未取回（本次响应没有丢行账本窗口）',
						},
					]}
				/>
			</Section>

			<Section title="事实定位" hint="按 §6.2 的七级顺序查同一项事实">
				<div className="xy-dig-factbar">
					<input
						type="text"
						value={needle}
						maxLength={400}
						placeholder="输入要定位的事实片段、来源 ID 或工具调用 ID"
						className="xy-dig-input"
						onChange={e => setNeedle(e.target.value)}
						onKeyDown={e => {
							if (e.key === 'Enter') void run();
						}}
					/>
					<button type="button" className="xy-dig-btn" disabled={busy} onClick={() => void run()}>
						{busy ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
						定位
					</button>
				</div>
				{err ? <Notice tone="fail">{err}</Notice> : null}
				{trace ? <FactChain trace={trace} /> : null}
			</Section>
		</div>
	);
}
