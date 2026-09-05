import {balanceInlineMd, hasStreamMarkdownSyntax} from '@/lib/streamMarkdown';
import {type CSSProperties, type ReactNode} from 'react';
import {LiveFadeText} from '@/components/LiveFadeText';

const INLINE_RE =
	/(`+)([^`]*?)\1|\*\*([^*]+)\*\*|\*([^*\s][^*]*?)\*|~~([^~]+)~~|!?\[([^\]]*)\]\(([^)]*)\)/g;

/**
 * 行内解析：吃「已 balance」文本，标记符不进 DOM。
 * 末尾 LiveFadeText；外层结构由调用方固定，避免 remount。
 */
function renderInlineWithFade(text: string): ReactNode[] {
	const nodes: ReactNode[] = [];
	let cursor = 0;
	INLINE_RE.lastIndex = 0;
	const matches: RegExpExecArray[] = [];
	let match: RegExpExecArray | null;
	while ((match = INLINE_RE.exec(text)) != null) {
		matches.push(match);
	}
	for (let mi = 0; mi < matches.length; mi += 1) {
		const m = matches[mi]!;
		const isLastToken = mi === matches.length - 1;
		if (m.index > cursor) {
			nodes.push(text.slice(cursor, m.index));
		}
		const key = `t-${m.index}`;
		const end = m.index + m[0].length;
		const isLineEnd = isLastToken && end >= text.length;
		const wrap = (inner: string, el: (child: ReactNode) => ReactNode) =>
			el(isLineEnd ? <LiveFadeText key={`${key}-f`} text={inner} /> : inner);

		if (m[1] != null) {
			nodes.push(
				wrap(m[2] ?? '', child => (
					<code
						key={key}
						className="rounded bg-paper-deep px-1 py-0.5 font-mono text-[0.85em] text-accent"
					>
						{child}
					</code>
				)),
			);
		} else if (m[3] != null) {
			nodes.push(wrap(m[3], child => <strong key={key}>{child}</strong>));
		} else if (m[4] != null) {
			nodes.push(wrap(m[4], child => <em key={key}>{child}</em>));
		} else if (m[5] != null) {
			nodes.push(wrap(m[5], child => <del key={key}>{child}</del>));
		} else if (m[6] != null) {
			nodes.push(
				wrap(m[6], child => (
					<span key={key} className="text-accent underline">
						{child}
					</span>
				)),
			);
		}
		cursor = end;
	}
	const tail = text.slice(cursor);
	if (tail) {
		nodes.push(<LiveFadeText key="fade" text={tail} />);
	} else if (nodes.length === 0) {
		nodes.push(<LiveFadeText key="fade" text={text} />);
	}
	return nodes;
}

function listBulletLabel(marker: string): string {
	const ordered = /^(\d+)[.)]\s*$/.exec(marker.trim());
	if (ordered) {
		return `${ordered[1]}.`;
	}
	return '•';
}

/**
 * 流式当前行唯一入口：raw text → 此处 balance 一次；
 * 始终同一套外层（p / blockquote / hr 占位），不在 chars/md 间 remount。
 */
export function LiveInlineMarkdown({text}: {text: string}) {
	const raw = text ?? '';
	const balanced = balanceInlineMd(raw);

	// 半截标题标记 → 不露 #
	if (/^(#{1,6})$/.test(balanced.trim())) {
		return (
			<p
				className="xy-live-prose xy-stream-live-md my-1.5 leading-6"
				style={{fontWeight: 650} as CSSProperties}
			>
				{'\u00a0'}
			</p>
		);
	}

	// HR：不把 --- 当明文（弱发丝线：border-line/70 等于最强 token --xy-rule-strong,
	// 视觉偏重;统一到软分割档 --xy-rule-weak 并用更松的上下间距）
	if (/^\s*(?:---|\*\*\*|___)\s*$/.test(balanced)) {
		return <hr className="xy-live-prose xy-stream-live-md my-4 border-line/40" />;
	}

	const heading = /^(#{1,6})\s+(.*)$/.exec(balanced);
	if (heading) {
		return (
			<p
				className="xy-live-prose xy-stream-live-md my-1.5 leading-6"
				style={{fontWeight: 650} as CSSProperties}
			>
				{renderInlineWithFade(heading[2] ?? '')}
			</p>
		);
	}
	const quote = /^>\s?(.*)$/.exec(balanced);
	if (quote) {
		return (
			<blockquote className="xy-live-prose xy-stream-live-md my-2 border-l-2 border-line pl-3 leading-6 text-ink-soft">
				{renderInlineWithFade(quote[1] ?? '')}
			</blockquote>
		);
	}
	const list = /^([ \t]*)([-*+]|\d+[.)])([ \t]+)(.*)$/.exec(balanced);
	if (list) {
		const marker = `${list[2]}${list[3] ?? ''}`;
		return (
			<p className="xy-live-prose xy-stream-live-md my-1.5 leading-6">
				<span className="mr-1.5 inline-block w-4 text-center text-mute" aria-hidden>
					{listBulletLabel(marker)}
				</span>
				{renderInlineWithFade(list[4] ?? '')}
			</p>
		);
	}

	// 无 markdown 语法：同一外层 p + LiveFadeText，不切组件类型
	if (!hasStreamMarkdownSyntax(balanced) && !hasStreamMarkdownSyntax(raw)) {
		return (
			<p className="xy-live-prose xy-stream-live-md my-1.5 leading-6">
				<LiveFadeText text={raw} />
			</p>
		);
	}

	return (
		<p className="xy-live-prose xy-stream-live-md my-1.5 leading-6">
			{renderInlineWithFade(balanced)}
		</p>
	);
}
