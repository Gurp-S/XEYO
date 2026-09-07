import {memo, useCallback, useEffect, useRef, useState} from 'react';
import {
	ArrowLeft,
	ArrowRight,
	ExternalLink,
	Globe,
	Loader2,
	RefreshCw,
} from 'lucide-react';
import {usePanelSubtitle} from '@/lib/panelSubtitle';
import {isTauri} from '@/lib/tauri';
import {cn} from '@/lib/utils';
import {useBrowserPreviewStore} from '@/stores/browserPreviewStore';

const BACKEND_ORIGIN = `http://127.0.0.1:${import.meta.env.VITE_XEYO_HTTP_PORT || '8000'}`;

const QUICK_URLS = [
	'http://localhost:5173',
	'http://localhost:3000',
	BACKEND_ORIGIN,
];

/** 把用户输入规范成可导航的 URL；空串返回 null。 */
function normalizeUrl(raw: string): string | null {
	const trimmed = raw.trim();
	if (!trimmed) {
		return null;
	}
	if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) {
		return trimmed;
	}
	if (
		trimmed.startsWith('localhost') ||
		trimmed.startsWith('127.0.0.1') ||
		trimmed.startsWith('[::1]')
	) {
		return `http://${trimmed}`;
	}
	return `https://${trimmed}`;
}

function hostLabel(url: string): string {
	try {
		return new URL(url).host || url;
	} catch {
		return url;
	}
}

async function openExternal(url: string): Promise<void> {
	if (isTauri()) {
		const {open} = await import('@tauri-apps/plugin-shell');
		await open(url);
		return;
	}
	window.open(url, '_blank', 'noopener,noreferrer');
}

/**
 * 工作区「浏览器」预览面板：地址栏 + iframe，仅供展示。
 * 经 browserPreviewStore 接收 XeyoUI `browser` 指令。
 */
export const BrowserPreviewPanel = memo(function BrowserPreviewPanel() {
	const storeUrl = useBrowserPreviewStore(s => s.url);
	const setStoreUrl = useBrowserPreviewStore(s => s.setUrl);
	const cmdSeq = useBrowserPreviewStore(s => s.seq);
	const cmd = useBrowserPreviewStore(s => s.cmd);

	const [draft, setDraft] = useState(storeUrl || 'http://localhost:5173');
	const [url, setUrl] = useState<string | null>(storeUrl);
	const [history, setHistory] = useState<string[]>(storeUrl ? [storeUrl] : []);
	const [cursor, setCursor] = useState(storeUrl ? 0 : -1);
	const [loading, setLoading] = useState(false);
	const [loadError, setLoadError] = useState(false);
	const [frameKey, setFrameKey] = useState(0);
	const inputRef = useRef<HTMLInputElement | null>(null);

	const historyRef = useRef(history);
	const cursorRef = useRef(cursor);
	const urlRef = useRef(url);
	historyRef.current = history;
	cursorRef.current = cursor;
	urlRef.current = url;

	const handledSeq = useRef(0);
	const booted = useRef(false);

	usePanelSubtitle(url ? hostLabel(url) : '预览');

	const applyUrl = useCallback(
		(next: string, push: boolean) => {
			setDraft(next);
			setUrl(next);
			setStoreUrl(next);
			setLoading(true);
			setLoadError(false);
			if (!push) {
				return;
			}
			const cur = cursorRef.current;
			const base =
				cur >= 0 ? historyRef.current.slice(0, cur + 1) : historyRef.current;
			if (base[base.length - 1] === next) {
				setCursor(base.length - 1);
				setHistory(base);
				return;
			}
			const merged = [...base, next].slice(-40);
			setHistory(merged);
			setCursor(merged.length - 1);
		},
		[setStoreUrl],
	);

	const navigateTo = useCallback(
		(raw: string, push = true) => {
			const next = normalizeUrl(raw);
			if (!next) {
				return;
			}
			applyUrl(next, push);
		},
		[applyUrl],
	);

	const goBack = useCallback(() => {
		const cur = cursorRef.current;
		if (cur <= 0) {
			return;
		}
		const next = cur - 1;
		const target = historyRef.current[next];
		if (!target) {
			return;
		}
		setCursor(next);
		setDraft(target);
		setUrl(target);
		setStoreUrl(target);
		setLoading(true);
		setLoadError(false);
	}, [setStoreUrl]);

	const goForward = useCallback(() => {
		const cur = cursorRef.current;
		const list = historyRef.current;
		if (cur < 0 || cur >= list.length - 1) {
			return;
		}
		const next = cur + 1;
		const target = list[next];
		if (!target) {
			return;
		}
		setCursor(next);
		setDraft(target);
		setUrl(target);
		setStoreUrl(target);
		setLoading(true);
		setLoadError(false);
	}, [setStoreUrl]);

	const reload = useCallback(() => {
		if (!urlRef.current) {
			return;
		}
		setLoading(true);
		setLoadError(false);
		setFrameKey(k => k + 1);
	}, []);

	useEffect(() => {
		if (!booted.current) {
			booted.current = true;
			// 挂载时若 store 已有 url（agent 先 setUrl 再开面板），视为已应用，只吃掉当前 seq。
			handledSeq.current = cmdSeq;
			if (storeUrl && storeUrl !== urlRef.current) {
				navigateTo(storeUrl);
			}
			return;
		}
		if (!cmd || cmdSeq === 0 || cmdSeq === handledSeq.current) {
			return;
		}
		handledSeq.current = cmdSeq;
		if (cmd.kind === 'nav') {
			navigateTo(cmd.url);
			return;
		}
		if (cmd.kind === 'reload') {
			reload();
			return;
		}
		if (cmd.kind === 'back') {
			goBack();
			return;
		}
		if (cmd.kind === 'fwd') {
			goForward();
			return;
		}
		if (cmd.kind === 'ext') {
			const target = urlRef.current;
			if (target) {
				void openExternal(target);
			}
		}
	}, [cmd, cmdSeq, storeUrl, navigateTo, reload, goBack, goForward]);

	useEffect(() => {
		if (!url) {
			return;
		}
		const timer = window.setTimeout(() => {
			setLoading(false);
		}, 12_000);
		return () => window.clearTimeout(timer);
	}, [url, frameKey]);

	return (
		<div className="flex h-full min-h-0 flex-col">
			<div className="flex shrink-0 items-center gap-1 border-b border-line/40 px-2 py-1.5">
				<button
					type="button"
					className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-40"
					aria-label="后退"
					title="后退"
					disabled={cursor <= 0}
					onClick={goBack}
				>
					<ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.8} />
				</button>
				<button
					type="button"
					className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-40"
					aria-label="前进"
					title="前进"
					disabled={cursor < 0 || cursor >= history.length - 1}
					onClick={goForward}
				>
					<ArrowRight className="h-3.5 w-3.5" strokeWidth={1.8} />
				</button>
				<button
					type="button"
					className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-40"
					aria-label="刷新"
					title="刷新"
					disabled={!url}
					onClick={reload}
				>
					<RefreshCw
						className={cn('h-3.5 w-3.5', loading && 'animate-spin')}
						strokeWidth={1.8}
					/>
				</button>
				<form
					className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-glass-hover/60 px-2 py-1"
					onSubmit={e => {
						e.preventDefault();
						navigateTo(draft);
					}}
				>
					<Globe className="h-3 w-3 shrink-0 text-mute" strokeWidth={1.8} />
					<input
						ref={inputRef}
						type="text"
						value={draft}
						onChange={e => setDraft(e.target.value)}
						onFocus={e => e.currentTarget.select()}
						placeholder="输入 URL，回车预览"
						aria-label="预览地址"
						spellCheck={false}
						autoComplete="off"
						className="min-w-0 flex-1 bg-transparent text-[12px] text-ink outline-none placeholder:text-mute/60"
					/>
				</form>
				<button
					type="button"
					className="xy-icon-btn shrink-0 rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-40"
					aria-label="在系统浏览器打开"
					title="在系统浏览器打开"
					disabled={!url}
					onClick={() => {
						if (url) {
							void openExternal(url);
						}
					}}
				>
					<ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
				</button>
			</div>

			{!url ? (
				<div className="xy-hover-scroll flex min-h-0 flex-1 flex-col items-stretch gap-3 overflow-auto px-4 py-6">
					<div className="mx-auto flex max-w-sm flex-col items-center gap-2 text-center">
						<div className="flex h-10 w-10 items-center justify-center rounded-full bg-glass-hover text-mute">
							<Globe className="h-5 w-5" strokeWidth={1.6} />
						</div>
						<p className="text-[13px] font-medium text-ink">浏览器预览</p>
						<p className="text-[12px] leading-relaxed text-mute">
							嵌入式预览，方便查看本地开发页或简单网页。部分站点会拒绝被嵌入，可改用系统浏览器打开。
						</p>
					</div>
					<div className="mx-auto flex w-full max-w-sm flex-col gap-1.5">
						<p className="px-0.5 text-[11px] text-mute">快捷地址</p>
						{QUICK_URLS.map(q => (
							<button
								key={q}
								type="button"
								onClick={() => navigateTo(q)}
								className="xy-pressable rounded-md px-2.5 py-1.5 text-left font-mono text-[12px] text-ink-soft hover:bg-glass-hover hover:text-ink"
							>
								{q}
							</button>
						))}
					</div>
				</div>
			) : (
				<div className="relative min-h-0 flex-1">
					{loading ? (
						<div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-1.5 bg-glass-strong/90 py-1 text-[11px] text-mute backdrop-blur-sm">
							<Loader2 className="h-3 w-3 animate-spin" />
							加载中…
						</div>
					) : null}
					{loadError ? (
						<div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-glass-strong px-4 text-center">
							<p className="text-[13px] text-ink">无法在预览中打开此页面</p>
							<p className="max-w-xs text-[12px] text-mute">
								目标站点可能禁止嵌入（X-Frame-Options / CSP）。可在系统浏览器中查看。
							</p>
							<button
								type="button"
								className="xy-pressable mt-1 rounded-md bg-glass-hover px-3 py-1.5 text-[12px] text-ink"
								onClick={() => void openExternal(url)}
							>
								在系统浏览器打开
							</button>
						</div>
					) : null}
					<iframe
						key={frameKey}
						title="浏览器预览"
						src={url}
						className="h-full w-full border-0 bg-white"
						referrerPolicy="no-referrer"
						sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"
						onLoad={() => {
							setLoading(false);
							setLoadError(false);
						}}
						onError={() => {
							setLoading(false);
							setLoadError(true);
						}}
					/>
				</div>
			)}
		</div>
	);
});
