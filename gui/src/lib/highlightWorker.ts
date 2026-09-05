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

self.onmessage = (ev: MessageEvent<HighlightRequest>) => {
	const {id, code, lang} = ev.data;
	try {
		const grammar = Prism.languages[lang] ?? Prism.languages.plain;
		const html = grammar
			? Prism.highlight(code, grammar, lang)
			: escapeHtml(code);
		const res: HighlightResponse = {id, ok: true, html};
		self.postMessage(res);
	} catch {
		const res: HighlightResponse = {id, ok: false};
		self.postMessage(res);
	}
};
