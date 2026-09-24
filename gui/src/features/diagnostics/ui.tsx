/**
 * features/diagnostics/ui.tsx — 诊断页共用的极小组件。
 *
 * 措辞纪律：这里只呈现事实与状态，不做评价性文案；色彩只来自 @theme token。
 */
import {type ReactNode, useState} from 'react';
import {Check, Copy} from 'lucide-react';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';
import type {DiagEvidenceRef} from '@/lib/api/diagnostics';
import {DASH, evidenceText} from './model';

export function Section({
	title,
	hint,
	children,
	dense,
}: {
	title: string;
	hint?: ReactNode;
	children: ReactNode;
	dense?: boolean;
}) {
	return (
		<section className={cn('xy-dig-section', dense && 'is-dense')}>
			<h3 className="xy-dig-section-title">
				{title}
				{hint ? <span className="xy-dig-section-hint">{hint}</span> : null}
			</h3>
			<div className="xy-dig-section-body">{children}</div>
		</section>
	);
}

export function Badge({
	tone = 'neutral',
	children,
}: {
	tone?: 'neutral' | 'ok' | 'warn' | 'fail' | 'waiting' | 'active' | 'confirmed' | 'suspect' | 'unknown';
	children: ReactNode;
}) {
	return <span className={cn('xy-dig-badge', `is-${tone}`)}>{children}</span>;
}

/** 空值一律破折号，不用 0 / 空白冒充。 */
export function Or({v}: {v: ReactNode}) {
	return <>{v == null || v === '' ? DASH : v}</>;
}

export function KeyValue({
	rows,
}: {
	rows: Array<{k: string; v: ReactNode; mono?: boolean}>;
}) {
	return (
		<dl className="xy-dig-kv">
			{rows.map(r => (
				<div className="xy-dig-kv-row" key={r.k}>
					<dt>{r.k}</dt>
					<dd className={cn(r.mono && 'font-mono')}>{r.v == null || r.v === '' ? DASH : r.v}</dd>
				</div>
			))}
		</dl>
	);
}

async function copyText(text: string): Promise<boolean> {
	// Tauri webview 下 Clipboard API 并非总可用，回退 execCommand（同 lib/workspaceOpen.ts）。
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		/* 继续走回退分支 */
	}
	try {
		const ta = document.createElement('textarea');
		ta.value = text;
		ta.setAttribute('readonly', '');
		ta.style.position = 'fixed';
		ta.style.left = '-9999px';
		document.body.appendChild(ta);
		ta.select();
		const ok = document.execCommand('copy');
		document.body.removeChild(ta);
		return ok;
	} catch {
		return false;
	}
}

/** 一条原始证据指针：点击复制 source | ref_id | locator（可复核，不复制正文）。 */
export function EvidenceChip({e}: {e: DiagEvidenceRef}) {
	const [copied, setCopied] = useState(false);
	const text = evidenceText(e);
	return (
		<button
			type="button"
			className="xy-dig-evidence"
			title={text}
			onClick={() => {
				void copyText(text).then(ok => {
					if (!ok) {
						toast.error('复制失败：证据定位未写入剪贴板');
						return;
					}
					setCopied(true);
					window.setTimeout(() => setCopied(false), 1200);
				});
			}}
		>
			{copied ? <Check className="size-3 shrink-0" aria-hidden /> : <Copy className="size-3 shrink-0" aria-hidden />}
			<span className="xy-dig-evidence-source">{e.source || DASH}</span>
			<span className="xy-dig-evidence-ref">{e.ref_id || DASH}</span>
			{e.detail ? <span className="xy-dig-evidence-detail">{e.detail}</span> : null}
			<span className="xy-dig-evidence-locator">{e.locator || DASH}</span>
		</button>
	);
}

export function EvidenceList({items}: {items: DiagEvidenceRef[]}) {
	if (!items.length) {
		return <p className="xy-dig-empty">无原始证据（因此不下定责结论）</p>;
	}
	return (
		<div className="xy-dig-evidence-list">
			{items.map((e, i) => (
				<EvidenceChip key={`${e.source}|${e.ref_id}|${e.detail}|${i}`} e={e} />
			))}
		</div>
	);
}

export function Notice({
	tone = 'neutral',
	children,
}: {
	tone?: 'neutral' | 'warn' | 'fail' | 'info';
	children: ReactNode;
}) {
	return <p className={cn('xy-dig-notice', `is-${tone}`)}>{children}</p>;
}
