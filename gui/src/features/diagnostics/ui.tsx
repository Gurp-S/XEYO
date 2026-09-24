/**
 * features/diagnostics/ui.tsx — 诊断页共用的极小组件。
 *
 * 措辞纪律：这里只呈现事实与状态，不做评价性文案；色彩只来自 @theme token。
 */
import {type ReactNode, useEffect, useRef, useState} from 'react';
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
	// 计时器必须复用同一个：连点两条证据时，如果每次点击都留一个自己的计时器，
	// 第一次那会在 1.2s 时把勾撤掉——而那一刻用户刚在第二次点击后看着它。
	const resetTimer = useRef<number | null>(null);
	// 剪贴板是异步的：切会话/换页会先卸载本组件，回调再 setState 或弹
	// "复制失败" 都成了对已经不存在的按钮说话。
	const alive = useRef(true);
	useEffect(
		() => () => {
			alive.current = false;
			if (resetTimer.current !== null) {
				window.clearTimeout(resetTimer.current);
				resetTimer.current = null;
			}
		},
		[],
	);
	const text = evidenceText(e);
	return (
		<button
			type="button"
			className="xy-dig-evidence"
			title={text}
			// 图标被 className 覆盖了 lucide 自带的类名，光秃的 svg 又 aria-hidden，
			// 所以"已复制"这个状态此前对读屏器完全不存在。给它一个真的可访问名。
			aria-label={copied ? '已复制证据定位' : '复制证据定位'}
			onClick={() => {
				void copyText(text).then(ok => {
					if (!alive.current) {
						return;
					}
					if (!ok) {
						toast.error('复制失败：证据定位未写入剪贴板');
						return;
					}
					setCopied(true);
					if (resetTimer.current !== null) {
						window.clearTimeout(resetTimer.current);
					}
					resetTimer.current = window.setTimeout(() => {
						resetTimer.current = null;
						setCopied(false);
					}, 1200);
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
