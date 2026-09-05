import {memo} from 'react';
import {useState} from 'react';
import {mediaUrl} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import {cn} from '@/lib/utils';
import {MarkdownView} from './MarkdownView';
import {StreamingMarkdown} from './StreamingMarkdown';
import {ThinkingLine} from './ThinkingLine';
import {UserMarkdownText} from './UserMarkdownText';
import {ImageReaderDialog, type ImageReaderSource} from './ImageReader';
import {ZoomIn} from 'lucide-react';

type Props = {
	message?: ChatMessage;
	streaming?: string;
	thinking?: string;
};

/** 仅全新消息播放动画 — 避免虚拟化回收时重播。 */
function enterClass(createdAt?: number) {
	if (createdAt === undefined) {
		return undefined;
	}
	return Date.now() - createdAt < 900 ? 'anim-rise' : undefined;
}

/** transcript 式布局：❯ user · ● assistant · ⎿ tool — 非聊天气泡。 */
function MessageBubbleInner({message, streaming, thinking}: Props) {
	const [previewImage, setPreviewImage] = useState<ImageReaderSource | null>(null);

	if (thinking && !streaming && !message) {
		return (
			<div className="anim-fade px-3 py-2 sm:px-5 md:px-8">
				<div className="mx-auto max-w-3xl">
					<ThinkingLine text={thinking} active />
				</div>
			</div>
		);
	}

	if (streaming !== undefined && streaming !== '') {
		return <StreamingBubble text={streaming} />;
	}

	if (!message) {
		return null;
	}

	if (message.role === 'user') {
		const remote = message.source === 'remote' || message.text.startsWith('[远程]');
		const body = remote
			? message.text.replace(/^\[远程\]\s*/, '')
			: message.text;
		return (
			<div
				className={cn(
					'px-3 py-2.5 sm:px-5 md:px-8',
					enterClass(message.createdAt),
				)}
			>
				<div className="xy-user-prompt xy-surface xy-user-bubble mx-auto max-w-3xl rounded-2xl px-4 pt-3.5 pb-2.5">
						{remote ? (
							<p className="mb-1 font-mono text-[10px] tracking-wide text-accent">
								[远程]
							</p>
						) : null}
													{message.mediaRefs?.length ? (
								<div className="mb-3 grid w-fit max-w-full grid-cols-[repeat(auto-fill,minmax(5.5rem,6.5rem))] gap-2">
									{message.mediaRefs.map((ref, index) => {
										const src = mediaUrl(ref);
										return src ? (
											<button
												key={`${ref}-${index}`}
												type="button"
												aria-label="查看已发送图片"
												onClick={event => {
													event.stopPropagation();
													setPreviewImage({src, alt: '已发送图片', title: '图片预览'});
												}}
												className="group relative aspect-square min-w-0 cursor-zoom-in overflow-hidden rounded-xl border border-line/70 bg-paper-deep/60 p-0 text-left"
											>
												{/* P4：屏外转写图片不提前解码（懒加载 + 异步解码），
												    容器 aspect-square 定尺寸，无布局位移。 */}
												<img src={src} alt="已发送图片" loading="lazy" decoding="async" className="h-full w-full object-cover" draggable={false} />
												<span className="pointer-events-none absolute right-1 bottom-1 flex h-6 w-6 items-center justify-center rounded-full bg-ink/60 text-paper opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
													<ZoomIn className="h-3.5 w-3.5" strokeWidth={1.9} />
												</span>
											</button>
										) : null;
									})}
								</div>
							) : null}

													<UserMarkdownText
								text={body}
								className="xy-chat-text min-w-0 font-sans text-[15px] leading-relaxed"
							/>
							<ImageReaderDialog image={previewImage} onClose={() => setPreviewImage(null)} />

				</div>
			</div>
		);
	}

	if (message.role === 'tool') {
		// 孤立 tool 行的回退；MessageList 优先使用 AssistantTurn 中的 ToolUseBlock。
		const running =
			message.toolStatus === 'running' || message.toolStatus === 'waiting';
		const input =
			message.toolInput ??
			(message.text.startsWith('call ') ? message.text.slice(5) : '');
		const result = running
			? ''
			: message.text.startsWith('call ')
				? ''
				: message.text;
		const errored =
			message.toolStatus === 'error' || result.startsWith('[error]');
		return (
			<div className="px-3 py-1 sm:px-5 md:px-8">
				<div className="mx-auto max-w-3xl pl-1 font-mono text-[12px]">
					{input ? (
						<div className="flex gap-2 text-mute">
							<span
								className={cn(
									'select-none',
									running ? 'blink-dot text-warn' : 'text-ink-soft',
								)}
							>
								●
							</span>
							<pre className="min-w-0 flex-1 whitespace-pre-wrap break-all">
								<span className="text-ink-soft">
									{message.toolName ?? 'tool'}
								</span>{' '}
								{input}
							</pre>
						</div>
					) : null}
					{!running || result ? (
						<div className="ml-4 flex gap-2">
							<span className={errored ? 'text-danger' : 'text-ok'}>⎿</span>
							<pre
								className={cn(
									'min-w-0 flex-1 whitespace-pre-wrap',
									errored ? 'text-danger' : 'text-ink-soft',
								)}
							>
								{result || '…'}
							</pre>
						</div>
					) : (
						<div className="ml-4 flex gap-2 text-mute">
							<span className="text-ok">⎿</span>
							<span>…</span>
						</div>
					)}
				</div>
			</div>
		);
	}

	if (message.role === 'system') {
		return (
			<div
				className={cn(
					'xy-chat-text px-3 py-2 text-center font-mono text-xs text-danger sm:px-5 md:px-8',
					enterClass(message.createdAt),
				)}
			>
				{message.text}
			</div>
		);
	}

	return (
		<div className={cn('px-3 py-2 sm:px-5 md:px-8', enterClass(message.createdAt))}>
			<div className="xy-prose-mark mx-auto max-w-3xl">
				<span className="xy-prose-dot" aria-hidden />
				<div className="xy-chat-text min-w-0 flex-1 font-sans text-[15px] leading-relaxed text-ink">
					<MarkdownView content={message.text} />
				</div>
			</div>
		</div>
	);
}

function StreamMarkdown({content}: {content: string}) {
	return (
		<div className="px-3 py-2 sm:px-5 md:px-8">
			<StreamingMarkdown className="mx-auto max-w-3xl" text={content} />
		</div>
	);
}

/** 远程镜像直接跟 SSE；揭示进度由 store.streamingShown 负责。 */
function StreamingBubble({text}: {text: string}) {
	return <StreamMarkdown content={text} />;
}

export const MessageBubble = memo(MessageBubbleInner, (prev, next) => {
	if (prev.thinking !== next.thinking) {
		return false;
	}
	if (prev.streaming !== next.streaming) {
		return false;
	}
	const a = prev.message;
	const b = next.message;
	if (a === b) {
		return true;
	}
	if (!a || !b) {
		return false;
	}
	return (
			a.id === b.id &&
			a.text === b.text &&
			a.role === b.role &&
			a.mediaRefs === b.mediaRefs &&
		a.toolName === b.toolName &&
		a.toolInput === b.toolInput &&
		a.toolStatus === b.toolStatus
	);
});
