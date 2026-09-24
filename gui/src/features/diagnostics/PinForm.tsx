/**
 * features/diagnostics/PinForm.tsx — 「标记这轮结果不对」表单（从 DiagnosticsPanel 抽出）。
 *
 * 独立成模块的原因是一条数据纪律：表单会把**当前展示的 detail** 的证据数组一起固定。
 * 因此调用方必须用 `key={sessionId}:{turnId}` 挂载它，并在换会话 / 换轮次时关掉，
 * 否则给 A 写的说明与 A 的证据会被按到 B 头上，后端还会拿它去判 B 的责任划分。
 */
import {useMemo, useState} from 'react';
import {Loader2} from 'lucide-react';
import {pinDiagRun, type DiagRunDetail} from '@/lib/api/diagnostics';
import {toast} from '@/lib/toast';
import {Notice} from './ui';

const MAX_EVIDENCE = 60;

export function PinForm({
	sessionId,
	turnId,
	detail,
	onDone,
}: {
	sessionId: string;
	turnId: string;
	detail: DiagRunDetail | null;
	onDone: () => void;
}) {
	const [note, setNote] = useState('');
	const [expected, setExpected] = useState('');
	const [pinEvidence, setPinEvidence] = useState(true);
	const [busy, setBusy] = useState(false);
	const [err, setErr] = useState('');

	const evidence = useMemo(() => {
		if (!detail || !pinEvidence) return [];
		const seen = new Set<string>();
		const out: DiagRunDetail['findings'][number]['evidence'] = [];
		for (const f of detail.findings) {
			for (const e of f.evidence) {
				const k = `${e.source}|${e.locator}|${e.ref_id}|${e.detail}`;
				if (seen.has(k)) continue;
				seen.add(k);
				out.push(e);
			}
		}
		for (const bd of detail.boundaries) {
			for (const e of bd.evidence) {
				const k = `${e.source}|${e.locator}|${e.ref_id}|${e.detail}`;
				if (seen.has(k)) continue;
				seen.add(k);
				if (out.length < MAX_EVIDENCE) out.push(e);
			}
		}
		return out.slice(0, MAX_EVIDENCE);
	}, [detail, pinEvidence]);

	return (
		<div className="xy-dig-pin">
			<label className="xy-dig-field">
				<span>这轮哪里不对（必填）</span>
				<textarea
					className="xy-dig-textarea"
					value={note}
					maxLength={4000}
					placeholder="只写观察到的事实与结果，不写推测"
					onChange={e => setNote(e.target.value)}
				/>
			</label>
			<label className="xy-dig-field">
				<span>预期结果</span>
				<textarea
					className="xy-dig-textarea"
					value={expected}
					maxLength={4000}
					placeholder="你期望这一轮产出什么"
					onChange={e => setExpected(e.target.value)}
				/>
			</label>
			<label className="xy-dig-check">
				<input
					type="checkbox"
					checked={pinEvidence}
					onChange={e => setPinEvidence(e.target.checked)}
				/>
				<span>
					固定证据（含本轮结论与边界证据{' '}
					{evidence.length ? `${evidence.length} 条` : '（当前无已取回正文）'}）
				</span>
			</label>
			<div className="xy-dig-actions">
				<button
					type="button"
					className="xy-dig-btn is-primary"
					disabled={busy || !note.trim()}
					onClick={() => {
						setBusy(true);
						setErr('');
						pinDiagRun(sessionId, turnId, {
							note: note.trim(),
							expected: expected.trim(),
							evidence,
						})
							.then(r => {
								if (!r.ok) {
									setErr(r.error || '固定失败：端点未接受该标记');
									return;
								}
								toast.success('已标记这轮结果并固定证据');
								setNote('');
								setExpected('');
								onDone();
							})
							.catch(e => setErr(e instanceof Error ? e.message : String(e)))
							.finally(() => setBusy(false));
					}}
				>
					{busy ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
					标记并固定
				</button>
			</div>
			{err ? <Notice tone="fail">{err}</Notice> : null}
			<Notice tone="info">
				标记只写入诊断目录的固定证据，不触发付费实验，也不修改任务内容。当前固定对象：本轮
				{turnId ? ` ${turnId}` : '（未选择轮次）'}。
			</Notice>
		</div>
	);
}
