import {useMemo, useRef, useState} from 'react';
import {parseMarkdownIntoBlocks} from 'streamdown';
import remend from 'remend';
import {StreamingMarkdown} from '@/components/StreamingMarkdown';
import {planTailFadeByBlocks} from '@/lib/rehypeTailFade';
import {createIncrementalRemend} from '@/lib/incrementalRemend';
import {createIncrementalBlockParse} from '@/lib/incrementalBlockParse';
import {xyRemendHandlers} from '@/lib/streamdownRemend';

const PARAS = Array.from(
	{length: 7},
	(_, i) => `## 段落 ${i + 1}\n\n${(`这是第${i + 1}段的流式正文内容，`).repeat(8)}`,
);
const DOC = [
	...PARAS,
	'- 列表项甲：包含一些较长的说明文字用来换行测试换行测试换行测试换行测试',
	'- 列表项乙：同样是较长的说明文字用来观察行首行尾的抖动情况观察抖动情况',
	`## 段落 8\n\n${'这是第8段的流式正文内容，'.repeat(10)}`,
].join('\n\n');

declare global {
	interface Window {
		__FADE_LAB__?: {
			reveal: (n: number) => void;
			auto: (ms?: number, step?: number) => void;
			stop: () => void;
			setDoc: (text: string) => void;
			benchParse: (text: string) => {
				lexMs: number;
				planMs: number;
				remendMs: number;
				blocks: number;
			};
			getState: () => {
				shownLen: number;
				total: number;
				doc: string;
			};
		};
		__SD_PARSE__?: (markdown: string) => string[];
		__SD_BLOCK_BENCH__?: {
			fullParse: (markdown: string) => string[];
			createIncrementalBlockParse: (
				parse?: (markdown: string) => string[],
			) => (markdown: string) => string[];
		};
		__SD_REMEND_BENCH__?: {
			remend: (text: string, options?: Record<string, unknown>) => string;
			handlers: unknown[];
			createIncrementalRemend: (
				options: Record<string, unknown>,
			) => (text: string) => string;
		};
	}
}

/** 临时实验路由：直接驱动 StreamingMarkdown 的展示文本（不依赖 rAF）。 */
export function FadeLabRoute() {
	const docRef = useRef<string>(DOC);
	const [shownLen, setShownLen] = useState(0);
	const lenRef = useRef(shownLen);
	lenRef.current = shownLen;
	const shown = useMemo(() => docRef.current.slice(0, shownLen), [shownLen]);
	const timerRef = useRef(0);

	window.__FADE_LAB__ = {
		reveal: n => setShownLen(Math.max(0, Math.min(docRef.current.length, n))),
		auto: (ms = 40, step = 3) => {
			window.clearInterval(timerRef.current);
			timerRef.current = window.setInterval(() => {
				if (lenRef.current >= docRef.current.length) {
					window.clearInterval(timerRef.current);
					return;
				}
				setShownLen(len => Math.min(docRef.current.length, len + step));
			}, ms);
		},
		stop: () => window.clearInterval(timerRef.current),
		setDoc: text => {
			docRef.current = text;
			setShownLen(0);
		},
		benchParse: text => {
			parseMarkdownIntoBlocks(text);
			const t0 = performance.now();
			const blocks = parseMarkdownIntoBlocks(text);
			const t1 = performance.now();
			planTailFadeByBlocks(blocks, 16);
			const t2 = performance.now();
			remend(text);
			const t3 = performance.now();
			return {
				lexMs: +(t1 - t0).toFixed(2),
				planMs: +(t2 - t1).toFixed(2),
				remendMs: +(t3 - t2).toFixed(2),
				blocks: blocks.length,
			};
		},
		getState: () => ({
			shownLen: lenRef.current,
			total: docRef.current.length,
			doc: docRef.current,
		}),
	};
	// 供控制台/基准脚本使用
	window.__SD_PARSE__ = parseMarkdownIntoBlocks;
	window.__SD_BLOCK_BENCH__ = {
		fullParse: parseMarkdownIntoBlocks,
		createIncrementalBlockParse,
	};
	window.__SD_REMEND_BENCH__ = {
		remend,
		handlers: xyRemendHandlers,
		createIncrementalRemend: opts =>
			createIncrementalRemend(
				opts as unknown as Parameters<typeof createIncrementalRemend>[0],
			),
	};

	return (
		<div className="h-screen w-full overflow-auto bg-paper py-8" data-fade-lab="">
			<div className="mx-auto max-w-2xl px-6">
				<StreamingMarkdown text={shown} />
			</div>
		</div>
	);
}
