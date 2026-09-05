// 必须最先求值：在 prismjs 之前伪装 document，阻断其 worker message 监听注册
// （否则每条高亮请求都会抛 JSON.parse "[object Object]" SyntaxError）。见 prismWorkerShim.ts。
import './prismWorkerShim';
import Prism from 'prismjs';
import 'prismjs/components/prism-clike';
import 'prismjs/components/prism-markup';
import 'prismjs/components/prism-css';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-markdown';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-csharp';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-ruby';
import 'prismjs/components/prism-kotlin';
import 'prismjs/components/prism-docker';

export type HighlightRequest = {
	id: number;
	code: string;
	lang: string;
};

export type HighlightResponse = {
	id: number;
	ok: boolean;
	html?: string;
};

function escapeHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

// 结果 LRU：虚拟列表滚回历史轮/跨会话切换/重开同一文件时，同一 (lang, code)
// 会被反复重发——缓存命中即零计算。LRU 触碰保证热条目存活。
const CACHE_LIMIT = 64;
const MAX_CACHED_CHARS = 200_000;
const resultCache = new Map<string, string>();

self.onmessage = (ev: MessageEvent<HighlightRequest>) => {
	const {id, code, lang} = ev.data;
	const key = `${lang}\u0000${code}`;
	const cached = resultCache.get(key);
	if (cached !== undefined) {
		resultCache.delete(key);
		resultCache.set(key, cached);
		self.postMessage({id, ok: true, html: cached} satisfies HighlightResponse);
		return;
	}
	try {
		const grammar = Prism.languages[lang] ?? Prism.languages.plain;
		const html = grammar
			? Prism.highlight(code, grammar, lang)
			: escapeHtml(code);
		if (code.length <= MAX_CACHED_CHARS) {
			resultCache.set(key, html);
			if (resultCache.size > CACHE_LIMIT) {
				const oldest = resultCache.keys().next().value;
				if (oldest !== undefined) {
					resultCache.delete(oldest);
				}
			}
		}
		const res: HighlightResponse = {id, ok: true, html};
		self.postMessage(res);
	} catch {
		const res: HighlightResponse = {id, ok: false};
		self.postMessage(res);
	}
};
