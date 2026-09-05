import {
	memo,
	useCallback,
	useEffect,
	useLayoutEffect,
	useRef,
	useState,
} from 'react';
import {cn} from '@/lib/utils';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';

/**
 * A8 Morph：与 workflow-anim-preview.html 合同一致。
 * 旧词 leave + 新词 enter（CSS keyframes），避免 rAF/prevVerb 状态机被取消后丢动画。
 * 仅在 verb 变化时翻面（如 Reading→Read）；禁止 live 期间无意义连转。
 */
export const MorphVerb = memo(function MorphVerb({
	verb,
	error,
}: {
	verb: string;
	/** @deprecated 保留兼容；不再用于连续 autoFlip */
	alt?: string;
	running?: boolean;
	error?: boolean;
	autoFlip?: boolean;
}) {
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const committedRef = useRef(verb);
	const [leaving, setLeaving] = useState<string | null>(null);
	const [enterGen, setEnterGen] = useState(0);

	useLayoutEffect(() => {
		if (committedRef.current === verb) {
			return;
		}
		const previous = committedRef.current;
		committedRef.current = verb;
		if (!smoothness) {
			setLeaving(null);
			setEnterGen(g => g + 1);
			return;
		}
		setLeaving(previous);
		setEnterGen(g => g + 1);
		const t = window.setTimeout(() => setLeaving(null), 360);
		return () => {
			window.clearTimeout(t);
		};
	}, [verb, smoothness]);

	const colorClass = error
		? 'is-error'
		: verb === 'Edited'
			? 'is-ok'
			: verb === 'Failed'
				? 'is-error'
				: undefined;

	return (
		<span className={cn('xy-morph shrink-0', colorClass)}>
			{leaving ? (
				<span className="is-leave" aria-hidden>
					{leaving}
				</span>
			) : null}
			<span
				key={enterGen}
				className={leaving && smoothness ? 'is-enter' : 'on'}
			>
				{verb}
			</span>
		</span>
	);
});

const PATHISH =
	/[\\/]|\.(?:tsx?|jsx?|json|css|md|py|rs|go|html)\b|[A-Za-z0-9_-]+\.(?:tsx?|jsx?|css|md)/;

export function tokenizeThought(text: string): string[] {
	const raw = text
		.split(/(?<=[。！？.!?\n])\s*|(?<=；|;)\s*|·|\s{2,}/)
		.map(s => s.trim())
		.filter(Boolean);
	if (raw.length === 0 && text.trim()) {
		return [text.trim()];
	}
	return raw;
}

export function thoughtTokenTier(token: string): 'primary' | 'secondary' {
	return PATHISH.test(token) ? 'secondary' : 'primary';
}

/**
 * L6 Kinetic 急促等宽 ticker —— 与 docs/l6-kinetic-preview.html 合同一致：
 * - 等宽字体（ui-monospace/Consolas），单行只滚最新思绪；
 * - 每次爆发 2-5 个字符（16-38ms 一拍），鼠标悬停减速（80-200ms）；
 * - 最新字符块紫色高亮（.xy-kinetic-hot），闪烁光标跟随；
 * - pinEnd：轨道右端钉住（translateX(tw - sw)）。
 *
 * 与预览的差异只在数据源：预览用固定 PHRASES，这里把流式 content
 * （tokenizeThought → ' · ' 连接）喂进同一个 burst 泵；轨道内容走
 * 命令式 innerHTML（与预览 pump 相同），避免 30-60Hz 的 React 重渲。
 */
export const ThoughtTicker = memo(function ThoughtTicker({
	content,
	running,
	collapsing,
	onToken,
}: {
	content: string;
	running?: boolean;
	collapsing?: boolean;
	onToken?: (token: string) => void;
}) {
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const tickerRef = useRef<HTMLDivElement>(null);
	const trackRef = useRef<HTMLDivElement>(null);
	const onTokenRef = useRef(onToken);
	onTokenRef.current = onToken;

	// 泵状态（全部 ref：pump 每 16-38ms 一次，不进 React state）。
	const pendingRef = useRef('');
	const shownRef = useRef('');
	const anchorRef = useRef('');
	const tokensRef = useRef<string[]>([]);
	const frontierRef = useRef(0); // full 线坐标：已消费到的绝对位置
	const tokenEndsRef = useRef<number[]>([]);
	const tokIdxRef = useRef(0);
	const timerRef = useRef(0);
	const hoveredRef = useRef(false);
	const pumpingRef = useRef(false);

	const escapeHtml = useCallback((s: string) => {
		return String(s)
			.replaceAll('&', '&amp;')
			.replaceAll('<', '&lt;')
			.replaceAll('>', '&gt;')
			.replaceAll('"', '&quot;');
	}, []);

	const pinEnd = useCallback(() => {
		const ticker = tickerRef.current;
		const track = trackRef.current;
		if (!ticker || !track) {
			return;
		}
		const tw = ticker.clientWidth;
		const sw = track.scrollWidth;
		track.style.transform =
			sw > tw ? `translateX(${tw - sw}px)` : 'translateX(0)';
	}, []);

	// 轨道节点一次性构建(2026-09-05 排查·嫌疑2):旧实现每拍 innerHTML 全量
	// 重建 DOM(16-38ms 一拍 ≈ 26-60Hz 的节点销毁/重建 + GC 压力)。改为
	// body/hot/cursor 三个持久节点 + textContent 原位更新,视觉等价
	// (.xy-kinetic-hot/.xy-thought-fresh 均为纯色样式,无逐拍重启动画)。
	const trackNodesRef = useRef<{
		body: HTMLSpanElement;
		hot: HTMLSpanElement;
		cursor: HTMLSpanElement;
	} | null>(null);

	const ensureTrackNodes = useCallback(() => {
		const track = trackRef.current;
		if (!track) {
			return null;
		}
		let nodes = trackNodesRef.current;
		if (!nodes || track.firstChild !== nodes.body) {
			// 静态路径/外部 reset 写过 innerHTML:重建持久节点。
			track.textContent = '';
			const body = document.createElement('span');
			body.className = 'xy-kinetic-body';
			const hot = document.createElement('span');
			hot.className = 'xy-kinetic-hot xy-thought-fresh';
			hot.style.display = 'none';
			const cursor = document.createElement('span');
			cursor.className = 'xy-thought-blink';
			cursor.setAttribute('aria-hidden', 'true');
			track.append(body, hot, cursor);
			nodes = {body, hot, cursor};
			trackNodesRef.current = nodes;
		}
		return nodes;
	}, []);

	const renderTrack = useCallback(
		(hot: string) => {
			const nodes = ensureTrackNodes();
			if (!nodes) {
				return;
			}
			nodes.body.textContent = shownRef.current;
			if (hot) {
				nodes.hot.textContent = hot;
				nodes.hot.style.display = '';
			} else {
				nodes.hot.style.display = 'none';
			}
			pinEnd();
		},
		[ensureTrackNodes, pinEnd],
	);

	/** 把新 content 增量喂进 pending；滑动尾窗（子 Agent 栏）按尾部对齐。 */
	const feed = useCallback(
		(full: string, tokens: string[]) => {
			const prev = anchorRef.current;
			let delta: string;
			if (full.startsWith(prev) && full.length >= prev.length) {
				delta = full.slice(prev.length);
			} else {
				// 尾窗滑动 / 整段替换：找旧串尾部在新串中的位置，只喂新增量。
				const tail = prev.slice(-32);
				const at = tail ? full.indexOf(tail) : -1;
				delta = at >= 0 ? full.slice(at + tail.length) : full.slice(-40);
			}
			anchorRef.current = full;
			tokensRef.current = tokens;
			pendingRef.current = (pendingRef.current + delta).slice(-200);
			// full 线坐标的 token 边界（' · ' 连接），供 onToken 按完成发射。
			let acc = 0;
			tokenEndsRef.current = tokens.map(t => {
				const end = acc + t.length;
				acc = end + 3; // ' · ' 分隔符
				return end;
			});
			frontierRef.current = Math.max(0, full.length - pendingRef.current.length);
			tokIdxRef.current = tokenEndsRef.current.findIndex(
				end => end > frontierRef.current,
			);
			if (tokIdxRef.current < 0) {
				tokIdxRef.current = tokens.length;
			}
		},
		[],
	);

	const pump = useCallback(() => {
		pumpingRef.current = true;
		const step = () => {
			if (!pendingRef.current) {
				// 排空：保留最后一帧（hot 块 + 闪烁光标），等下一波 content；
				// 尚无任何内容时至少画闪烁光标（与预览 resetAnimation 一致）。
				pumpingRef.current = false;
				if (!shownRef.current) {
					renderTrack('');
				}
				return;
			}
			// L6 burst：2-5 字符/拍；不劈开代理对。
			let burst = 2 + Math.floor(Math.random() * 4);
			const pending = pendingRef.current;
			const cut = Math.min(burst, pending.length);
			const last = pending.charCodeAt(cut - 1);
			if (last >= 0xd800 && last <= 0xdbff && cut < pending.length) {
				burst = cut + 1;
			}
			const chunk = pending.slice(0, burst);
			pendingRef.current = pending.slice(burst);
			let shown = shownRef.current + chunk;
			if (shown.length > 170) {
				shown = shown.slice(-130);
				// 尾窗裁剪不劈开代理对。
				const c0 = shown.charCodeAt(0);
				if (c0 >= 0xdc00 && c0 <= 0xdfff) {
					shown = shown.slice(1);
				}
			}
			shownRef.current = shown;
			frontierRef.current += chunk.length;
			const ends = tokenEndsRef.current;
			while (
				tokIdxRef.current < ends.length &&
				ends[tokIdxRef.current]! <= frontierRef.current
			) {
				onTokenRef.current?.(tokensRef.current[tokIdxRef.current] ?? '');
				tokIdxRef.current += 1;
			}
			renderTrack(chunk);
			// L6 节奏：急促 16-38ms；悬停减速 80-200ms。
			const delay = hoveredRef.current
				? 80 + Math.random() * 120
				: 16 + Math.random() * 22;
			timerRef.current = window.setTimeout(step, delay);
		};
		step();
	}, [renderTrack]);

	useEffect(() => {
		const live = Boolean(running) && smoothness;
		if (!live) {
			window.clearTimeout(timerRef.current);
			timerRef.current = 0;
			pumpingRef.current = false;
			pendingRef.current = '';
			// 平滑关闭 / 已停止：静态尾窗（与旧 L10 的 slice(-6) 对齐）。
			const tokens = tokenizeThought(content);
			const track = trackRef.current;
			if (track) {
				const tail = tokens.slice(-6).join(' · ');
				track.innerHTML = tail
					? `<span class="xy-kinetic-body">${escapeHtml(tail)}</span>`
					: '';
				if (trackRef.current && tickerRef.current) {
					trackRef.current.style.transform = 'translateX(0)';
				}
			}
			return;
		}
		const tokens = tokenizeThought(content);
		const full = tokens.join(' · ');
		feed(full, tokens);
		if (!pumpingRef.current) {
			pump();
		}
		return () => {
			window.clearTimeout(timerRef.current);
			timerRef.current = 0;
			pumpingRef.current = false;
		};
	}, [content, running, smoothness, feed, pump, escapeHtml]);

	useEffect(() => {
		return () => {
			window.clearTimeout(timerRef.current);
		};
	}, []);

	if (!content.trim() && !running) {
		return <span className="xy-thought-settled">—</span>;
	}

	const settled = !running && !collapsing;
	if (settled && content.trim()) {
		return (
			<span className="xy-thought-settled">
				{content.trim().replace(/\s+/g, ' ')}
			</span>
		);
	}

	// live / 静态共用同一轨道节点：内容全部由 effect 命令式写入
	// （与预览 pump 相同），避免 React children 与 innerHTML 打架。
	return (
		<div
			ref={tickerRef}
			className={cn('xy-thought-ticker', collapsing && 'is-collapsing')}
			onMouseEnter={() => {
				hoveredRef.current = true;
			}}
			onMouseLeave={() => {
				hoveredRef.current = false;
			}}
		>
			<div ref={trackRef} className="xy-thought-ticker-track" />
		</div>
	);
});
