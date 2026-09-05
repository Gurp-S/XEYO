import {Check, ChevronDown, ChevronRight, Copy} from 'lucide-react';
import {lazy, memo, Suspense, useEffect, useRef, useState} from 'react';
import {useHoverScroll} from '@/hooks/useHoverScroll';
import {highlightCode} from '@/lib/highlightClient';
import {cn} from '@/lib/utils';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {isDarkScheme} from '@/theme/catalog';

/** 主线程高亮兜底,懒加载(独立 chunk):react-syntax-highlighter + 28 个 refractor
    语言定义不进主 bundle,仅在 worker 不可用/失败的首个代码块命中时才下载。 */
const FallbackHighlighter = lazy(() => import('./FallbackHighlighter'));

type Props = {
	language?: string;
	value: string;
	/** 自动折叠长代码块。流式期间禁用以避免闪烁。 */
	autoCollapse?: boolean;
	/** 文件预览：无卡片边框，带行号，铺满栏。 */
	variant?: 'chat' | 'file';
};

/** 规范化 Prism 可能不认识的 language 标签 → 安全回退。 */
export function normalizeHighlightLanguage(language: string | undefined): string {
	const raw = (language || 'text').trim().toLowerCase();
	if (!raw || raw === 'text' || raw === 'plaintext' || raw === 'plain') {
		return 'text';
	}
	const aliases: Record<string, string> = {
		js: 'javascript',
		jsx: 'jsx',
		ts: 'typescript',
		tsx: 'tsx',
		py: 'python',
		rb: 'ruby',
		sh: 'bash',
		shell: 'bash',
		zsh: 'bash',
		yml: 'yaml',
		md: 'markdown',
		csharp: 'csharp',
		'c#': 'csharp',
		'c++': 'cpp',
		golang: 'go',
		rs: 'rust',
		kt: 'kotlin',
		dockerfile: 'docker',
	};
	const cleaned = aliases[raw] ?? raw.replace(/[^a-z0-9#+.-]/g, '');
	return cleaned || 'text';
}

function CodeBlockInner({
	language = 'text',
	value,
	autoCollapse = true,
	variant = 'chat',
}: Props) {
	const lineCountRef = useRef<{value: string; lines: number}>({
		value: '',
		lines: 1,
	});
	let lines = lineCountRef.current.lines;
	if (value !== lineCountRef.current.value) {
		if (value.startsWith(lineCountRef.current.value)) {
			const suffix = value.slice(lineCountRef.current.value.length);
			for (const char of suffix) {
				if (char === '\n') {
					lines += 1;
				}
			}
		} else {
			lines = value.length === 0 ? 1 : 1;
			for (const char of value) {
				if (char === '\n') {
					lines += 1;
				}
			}
		}
		lineCountRef.current = {value, lines};
	}
	const [collapsed, setCollapsed] = useState(
		() => autoCollapse && lines > 16,
	);
	const [copied, setCopied] = useState(false);
	const theme = useSettingsStore(s => s.theme);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const dark = isDarkScheme(theme);
	const lang = normalizeHighlightLanguage(language);
	const langLabel = (language || 'text').trim() || 'text';
	const file = variant === 'file';
	/** 流式 fence 跳过 Prism；文件预览强制走 worker，避免大文件打开时
	    Prism 在主线程同步高亮造成卡顿（worker 完成前先显示纯文本）。 */
	const skipPrism = smoothness && !autoCollapse && !file;
	const useWorker = (smoothness || file) && !skipPrism;
	const [workerHtml, setWorkerHtml] = useState<string | null>(null);
	const [workerFailed, setWorkerFailed] = useState(false);
	const lastGoodHtml = useRef<string | null>(null);

	const lastPosted = useRef('');

	useEffect(() => {
		if (!useWorker) {
			return;
		}
		const key = `${lang}\n${value}`;
		if (key === lastPosted.current) {
			return;
		}
		let cancelled = false;
		void highlightCode(lang, value).then(html => {
			if (cancelled) {
				return;
			}
			lastPosted.current = key;
			if (html != null) {
				lastGoodHtml.current = html;
				setWorkerFailed(false);
				setWorkerHtml(html);
				return;
			}
			if (lastGoodHtml.current != null) {
				setWorkerHtml(lastGoodHtml.current);
				setWorkerFailed(false);
				return;
			}
			setWorkerFailed(true);
		});
		return () => {
			cancelled = true;
		};
	}, [lang, useWorker, value]);

	// 流式禁用自动折叠；保持展开。最终消息可折叠。
	useEffect(() => {
		if (!autoCollapse) {
			setCollapsed(false);
			return;
		}
		if (lines > 16) {
			setCollapsed(true);
		}
	}, [autoCollapse, lines]);

	const onCopy = async () => {
		try {
			await navigator.clipboard.writeText(value);
			setCopied(true);
			setTimeout(() => setCopied(false), 1500);
		} catch {
			/* 忽略 */
		}
	};

	const hover = useHoverScroll();
	const gutter = file
		? Array.from({length: lines}, (_, i) => String(i + 1)).join('\n')
		: '';
	const useHighlighter = !skipPrism && (!useWorker || workerFailed);
	const filePlain = (
		<div className="xy-prism-file flex min-h-0">
			<pre aria-hidden className="xy-prism-gutter m-0">
				{gutter}
			</pre>
			<pre className="xy-prism-html m-0 min-w-0 flex-1 whitespace-pre">
				<code>{value || ' '}</code>
			</pre>
		</div>
	);
	const plainPre = (
		<pre className="xy-prism-html m-0 whitespace-pre-wrap break-all">
			<code>{value || ' '}</code>
		</pre>
	);
	const codeBody = skipPrism ? (
		plainPre
	) : useHighlighter ? (
		<Suspense fallback={file ? filePlain : plainPre}>
			<FallbackHighlighter
				lang={lang}
				dark={dark}
				file={file}
				value={value}
				customStyle={{
					margin: 0,
					padding: file
						? '8px 16px 16px 12px'
						: collapsed
							? '10px 14px 0 16px'
							: '12px 14px 12px 16px',
					background: 'transparent',
					fontSize: '13px',
				}}
			/>
		</Suspense>
	) : useWorker && workerHtml != null && file ? (
		<div className="xy-prism-file flex min-h-0">
			<pre aria-hidden className="xy-prism-gutter m-0">
				{gutter}
			</pre>
			<pre
				className="xy-prism-html m-0 min-w-0 flex-1"
				dangerouslySetInnerHTML={{__html: workerHtml}}
			/>
		</div>
	) : useWorker && workerHtml != null ? (
		<pre
			className="xy-prism-html m-0"
			dangerouslySetInnerHTML={{__html: workerHtml}}
		/>
	) : (
		filePlain
	);

	return (
		<div
			className={cn(
				file
					? 'xy-code-file flex min-h-0 flex-1 flex-col'
					: 'xy-md-surface xy-code-surface my-2.5 overflow-hidden rounded-xl border',
			)}
		>
			<div
				className={cn(
					'flex items-center justify-between gap-2 px-3 py-1.5 text-xs text-mute',
					file
						? 'border-b border-line/30'
						: 'border-b border-rule-strong',
				)}
			>
				<button
					type="button"
					className="inline-flex min-w-0 items-center gap-1.5 hover:text-ink"
					onClick={() => setCollapsed(v => !v)}
					aria-expanded={!collapsed}
				>
					{collapsed ? (
						<ChevronRight className="h-3.5 w-3.5 shrink-0" />
					) : (
						<ChevronDown className="h-3.5 w-3.5 shrink-0" />
					)}
					<span
						className={cn(
							'font-medium uppercase tracking-wide text-ink-soft',
							!file &&
								'rounded-md bg-glass-strong px-1.5 py-0.5 ring-1 ring-rule',
						)}
					>
						{langLabel}
					</span>
					<span className="shrink-0 text-mute/80">{lines} 行</span>
				</button>
				<button
					type="button"
					onClick={() => void onCopy()}
					className={cn(
						'inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-mute transition-colors hover:bg-glass-hover hover:text-ink',
						!file &&
							'hover:ring-1 hover:ring-rule-strong dark:hover:bg-white/12 dark:hover:text-ink dark:hover:ring-white/20',
					)}
				>
					{copied ? (
						<>
							<Check className="h-3.5 w-3.5 text-ok" />
							已复制
						</>
					) : (
						<>
							<Copy className="h-3.5 w-3.5" />
							复制
						</>
					)}
				</button>
			</div>
			<div
				ref={file ? hover.scrollerRef : undefined}
				onMouseEnter={file ? hover.onMouseEnter : undefined}
				onMouseLeave={file ? hover.onMouseLeave : undefined}
				className={cn(
					'relative text-[13px] leading-5',
					file
						? 'xy-hover-scroll min-h-0 flex-1 overflow-auto'
						: 'overflow-x-auto',
					collapsed && 'max-h-[2.75rem] overflow-y-hidden',
				)}
			>
				{codeBody}
				{collapsed ? (
					<div
						aria-hidden
						className="xy-code-fade pointer-events-none absolute inset-x-0 bottom-0 h-5"
					/>
				) : null}
			</div>
			{collapsed && (
				<button
					type="button"
					onClick={() => setCollapsed(false)}
					className="w-full border-t border-rule-strong py-1.5 text-center text-xs text-accent transition-colors hover:bg-glass-soft/50"
				>
					展开全部代码
				</button>
			)}
		</div>
	);
}

export const CodeBlock = memo(CodeBlockInner);
