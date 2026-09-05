import {
	memo,
	useContext,
	useMemo,
	useRef,
	createContext,
	type ReactNode,
} from 'react';
import {
	Streamdown,
	Block,
	defaultRemarkPlugins,
	type BlockProps,
	type Components,
} from 'streamdown';
import {math as streamdownMath} from '@streamdown/math';
import {cjk as streamdownCjk} from '@streamdown/cjk';
import rehypeSlug from 'rehype-slug';
import {ZoomIn} from 'lucide-react';
import 'katex/dist/katex.min.css';
import 'streamdown/styles.css';
import {cn} from '@/lib/utils';
import {resolveMdHref} from '@/lib/mdHref';
import {remarkUnderline} from '@/lib/remarkUnderline';
import {remarkChatBreaks} from '@/lib/remarkChatBreaks';
import {xyRemendHandlers} from '@/lib/streamdownRemend';
import {createIncrementalRemend} from '@/lib/incrementalRemend';
import {createIncrementalBlockParse, type BlockParseFn} from '@/lib/incrementalBlockParse';
import {parseStaticBlocks} from '@/lib/markdownStaticCache';
import {createRehypeTailFade, planTailFadeByBlocks} from '@/lib/rehypeTailFade';
import {rehypeSafeHtml} from '@/lib/rehypeSafeHtml';
import {useExplorerStore} from '@/stores/explorerStore';
import {CodeBlock} from './CodeBlock';
import {MermaidBlock} from './MermaidBlock';
import {WorkspaceImg} from './WorkspaceImg';
import {XeyoMapFence} from './XeyoMapFence';

/** 流式全文末尾渐变码点数（固定）。 */
const TAIL_FADE_CHARS = 16;

export type XyStreamdownProps = {
	content: string;
	className?: string;
	/** true：streaming + 增量 remend + 末尾 N 字渐变；false：static 落盘。 */
	streaming?: boolean;
	/** 流式时跳过 math 插件，减轻半成品公式撑跳。 */
	lite?: boolean;
	codeAutoCollapse?: boolean;
	basePath?: string;
	onOpenPath?: (path: string, hash?: string) => void;
	editable?: boolean;
	/** 图片点击放大（文件预览）。 */
	onImagePreview?: (src: string, alt: string) => void;
	/** 聊天口径：段落内单换行渲染为 <br>（用户气泡 / Composer 预览）。 */
	breaks?: boolean;
};

const TailFadeCtx = createContext<{
	plans: {fadeCount: number}[];
}>({plans: []});

/** 每个 block 按全局尾部窗口挂渐变（不限 lastIndex）。 */
const XyTailFadeBlock = memo(function XyTailFadeBlock(props: BlockProps) {
	const {plans} = useContext(TailFadeCtx);
	const fadeCount = plans[props.index]?.fadeCount ?? 0;
	const rehypePlugins = useMemo(() => {
		const base = props.rehypePlugins ?? [];
		if (fadeCount <= 0) {
			return base;
		}
		return [...base, createRehypeTailFade(fadeCount)];
	}, [props.rehypePlugins, fadeCount]);
	return <Block {...props} rehypePlugins={rehypePlugins} />;
});

function scrollToHeading(id: string) {
	document.getElementById(id)?.scrollIntoView({block: 'start', behavior: 'smooth'});
}

function fenceLock(
	editable: boolean | undefined,
	lang: string,
	code: string,
	node: ReactNode,
) {
	if (!editable) {
		return node;
	}
	return (
		<div contentEditable={false} data-md-fence={lang} data-md-code={code}>
			{node}
		</div>
	);
}

/**
 * 聊天 / 预览共用的唯一 Markdown 渲染内核（Streamdown）。
 * 打字机仍由 store.streamingShown 驱动；流式末尾 N 字 rehype 渐变。
 * remend 在 App 层增量完成（createIncrementalRemend）：
 * Streamdown 内部的全量 remend 是每帧 O(全文) 的配对扫描，长文必掉帧，故关闭。
 */
export const XyStreamdown = memo(function XyStreamdown({
	content,
	className,
	streaming = false,
	lite = false,
	codeAutoCollapse = true,
	basePath = '',
	onOpenPath,
	editable = false,
	onImagePreview,
	breaks = false,
}: XyStreamdownProps) {
	const remendRef = useRef<((text: string) => string) | null>(null);
	if (streaming && remendRef.current === null) {
		remendRef.current = createIncrementalRemend({handlers: xyRemendHandlers});
	}
	const displayContent =
		streaming && remendRef.current ? remendRef.current(content) : content;

	// 增量分块：同一个实例同时服务 fadePlans 与 Streamdown 内部，
	// 第二次调用命中缓存，每帧只做一次 O(增量) 的 lex。
	// static（settled）消息改走模块级 LRU（P1-①）：滚动窗口 / 会话切换
	// 重挂载时同 content 引用直接命中，输出与全量解析逐字节相同。
	const parseRef = useRef<BlockParseFn | null>(null);
	if (parseRef.current === null) {
		parseRef.current = streaming ? createIncrementalBlockParse() : parseStaticBlocks;
	}
	const incrementalParse = parseRef.current;

	const fadeWindow = streaming ? TAIL_FADE_CHARS : 0;

	const fadePlans = useMemo(() => {
		if (!streaming || fadeWindow <= 0) {
			return [] as {fadeCount: number}[];
		}
		// 必须与 Streamdown 实际解析的文本一致（内部不再做 remend）
		return planTailFadeByBlocks(incrementalParse(displayContent), fadeWindow);
	}, [streaming, displayContent, fadeWindow, incrementalParse]);

	const plugins = useMemo(() => {
		if (lite || streaming) {
			return {cjk: streamdownCjk};
		}
		return {math: streamdownMath, cjk: streamdownCjk};
	}, [lite, streaming]);

	const remarkPlugins = useMemo(
		() => [
			defaultRemarkPlugins.gfm,
			defaultRemarkPlugins.codeMeta,
			remarkUnderline,
			// 注意：传插件工厂本身（unified 会调用它拿 transformer），
			// 不能传 remarkChatBreaks() 的返回值。
			...(breaks ? [remarkChatBreaks] : []),
		],
		[breaks],
	);

	const rehypePlugins = useMemo(
		() => [
			// 原始 HTML 安全渲染（白名单，含 rehype-raw 本体）须在最前，
			// slug / 尾迹渐变在其后。
			...rehypeSafeHtml,
			// 不用 default sanitize/harden：会拆掉 <u>、改写相对链接与尾斜杠。
			// 链接安全走 resolveMdHref；尾迹渐变在 BlockComponent 里挂在 slug 之后。
			rehypeSlug,
		],
		[],
	);

	const components = useMemo((): Components => {
		const wrapImage = (node: ReactNode, previewSrc: string, alt: string) => {
			if (!onImagePreview || !previewSrc) {
				return node;
			}
			return (
				<button
					type="button"
					aria-label={`查看图片：${alt || 'Markdown 图片'}`}
					onClick={() => onImagePreview(previewSrc, alt)}
					className="group relative my-2 block max-w-full cursor-zoom-in border-0 bg-transparent p-0 text-left"
				>
					{node}
					<span className="pointer-events-none absolute right-2 bottom-2 flex h-7 w-7 items-center justify-center rounded-full bg-ink/60 text-paper opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
						<ZoomIn className="h-3.5 w-3.5" strokeWidth={1.9} />
					</span>
				</button>
			);
		};

		return {
			p: ({children}) => (
				<p className="my-1.5 leading-6 text-ink">{children}</p>
			),
			strong: ({children}) => (
				<strong className="font-bold text-ink">{children}</strong>
			),
			em: ({children}) => <em>{children}</em>,
			ul: ({children}) => (
				<ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>
			),
			ol: ({children}) => (
				<ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>
			),
			li: ({children}) => <li className="leading-6">{children}</li>,
			blockquote: ({children}) => (
				<blockquote className="my-2 border-l-2 border-line pl-3 text-ink-soft">
					{children}
				</blockquote>
			),
			h1: ({children, id}) => (
				<h1 id={id} className="mb-2 mt-3 text-xl font-semibold text-ink">
					{children}
				</h1>
			),
			h2: ({children, id}) => (
				<h2 id={id} className="mb-2 mt-3 text-lg font-semibold text-ink">
					{children}
				</h2>
			),
			h3: ({children, id}) => (
				<h3 id={id} className="mb-1.5 mt-2.5 text-base font-semibold text-ink">
					{children}
				</h3>
			),
			h4: ({children, id}) => (
				<h4 id={id} className="mb-1.5 mt-2 text-[15px] font-semibold text-ink">
					{children}
				</h4>
			),
			h5: ({children, id}) => (
				<h5 id={id} className="mb-1 mt-2 text-sm font-semibold text-ink">
					{children}
				</h5>
			),
			h6: ({children, id}) => (
				<h6 id={id} className="mb-1 mt-2 text-sm font-medium text-ink-soft">
					{children}
				</h6>
			),
			hr: () => <hr className="my-4 border-line/40" />,
			a: ({href, children}) => {
				const dest = resolveMdHref(href, basePath);
				const lock = editable ? {contentEditable: false as const} : {};
				if (dest.kind === 'unsafe') {
					return <span className="text-ink-soft">{children}</span>;
				}
				if (dest.kind === 'hash') {
					return (
						<a
							href={`#${dest.id}`}
							className="text-accent underline"
							{...lock}
							onClick={e => {
								e.preventDefault();
								scrollToHeading(dest.id);
							}}
						>
							{children}
						</a>
					);
				}
				if (dest.kind === 'local') {
					return (
						<a
							href={href}
							className="text-accent underline"
							{...lock}
							onClick={e => {
								e.preventDefault();
								if (onOpenPath) {
									onOpenPath(dest.path, dest.hash);
									return;
								}
								void useExplorerStore.getState().openFile(dest.path);
							}}
						>
							{children}
						</a>
					);
				}
				return (
					<a
						href={dest.href}
						target="_blank"
						rel="noreferrer"
						className="text-accent underline"
						{...lock}
					>
						{children}
					</a>
				);
			},
			img: ({src, alt}) => {
				const label = alt || '';
				if (src && /^(https?:|data:image\/)/i.test(src)) {
					return wrapImage(
						<img
							src={src}
							alt={label}
							className="block max-h-[28rem] max-w-full rounded-lg border border-line/50"
						/>,
						src,
						label,
					);
				}
				const dest = resolveMdHref(src, basePath);
				if (dest.kind === 'local') {
					return wrapImage(
						<WorkspaceImg path={dest.path} alt={label} />,
						src || dest.path,
						label,
					);
				}
				return wrapImage(
					<span className="text-mute">{label || '[image]'}</span>,
					src || '',
					label,
				);
			},
			code: ({className: cls, children, ...props}) => {
				const match = /language-([\w#+.-]+)/.exec(cls || '');
				const text = String(children).replace(/\n$/, '');
				const lang = (match?.[1] || '').toLowerCase();
				const inline = !match && !text.includes('\n');
				if (inline) {
					return (
						<code
							className="rounded bg-paper-deep px-1 py-0.5 font-mono text-[0.85em] text-accent"
							{...props}
						>
							{children}
						</code>
					);
				}
				if (lang === 'mermaid' && !lite && !streaming) {
					return fenceLock(editable, 'mermaid', text, <MermaidBlock source={text} />);
				}
				if (
					(lang === 'xeyo-map' || lang === 'xeyomap') &&
					!lite &&
					!streaming
				) {
					return fenceLock(
						editable,
						'xeyo-map',
						text,
						<XeyoMapFence source={text} />,
					);
				}
				return fenceLock(
					editable,
					match?.[1] || '',
					text,
					<div className="xy-code-surface xy-stream-code">
						<CodeBlock
							language={match?.[1] || 'text'}
							value={text}
							autoCollapse={codeAutoCollapse}
						/>
					</div>,
				);
			},
			pre: ({children}) => <>{children}</>,
			table: ({children}) => (
				<div className="xy-md-surface my-2.5 overflow-x-auto rounded-xl border border-line/55 px-0 py-0">
					<table className="w-full border-collapse text-left text-[13px]">
						{children}
					</table>
				</div>
			),
			th: ({children}) => (
				<th className="border-b border-line/50 bg-glass-soft/50 px-2.5 py-1.5 font-medium text-ink first:pl-3 last:pr-3">
					{children}
				</th>
			),
			td: ({children}) => (
				<td className="border-b border-line/35 px-2.5 py-1.5 text-ink-soft first:pl-3 last:pr-3 last:border-b-0">
					{children}
				</td>
			),
			u: ({children}) => (
				<u className="underline decoration-ink underline-offset-2">{children}</u>
			),
		};
	}, [
		basePath,
		codeAutoCollapse,
		editable,
		lite,
		onImagePreview,
		onOpenPath,
		streaming,
	]);

	const fadeCtx = useMemo(() => ({plans: fadePlans}), [fadePlans]);

	return (
		<TailFadeCtx.Provider value={fadeCtx}>
			<Streamdown
				className={cn(
					'xy-streamdown',
					streaming && 'xy-streamdown-live',
					className,
				)}
				mode={streaming ? 'streaming' : 'static'}
				parseIncompleteMarkdown={false}
				parseMarkdownIntoBlocksFn={incrementalParse}
				plugins={plugins}
				components={components}
				remarkPlugins={remarkPlugins}
				rehypePlugins={rehypePlugins}
				BlockComponent={streaming ? XyTailFadeBlock : Block}
				controls={false}
				lineNumbers={false}
				codeBlockMaxHeight={0}
				tableMaxHeight={0}
				linkSafety={{enabled: false}}
				isAnimating={false}
				animated={false}
				shikiTheme={['github-light', 'github-dark']}
			>
				{displayContent}
			</Streamdown>
		</TailFadeCtx.Provider>
	);
});
