import {cn} from '@/lib/utils';
import {stripXmlToolCallsForDisplay} from '@/lib/stripXmlToolCalls';
import {memo} from 'react';
import {XyStreamdown} from './XyStreamdown';
import './streamingMarkdown.css';

/**
 * 聊天流式 / 落盘正文：唯一内核 Streamdown。
 * 打字机由 streamingShown 驱动；流式强制末尾 N 字渐变；落盘同树 static、无渐变。
 */
export const StreamingMarkdown = memo(function StreamingMarkdown({
	text,
	className,
	final: isFinal = false,
	codeAutoCollapse = false,
}: {
	text: string;
	className?: string;
	/** 落盘：static 模式，可折叠代码块。 */
	final?: boolean;
	codeAutoCollapse?: boolean;
}) {
	const cleaned = stripXmlToolCallsForDisplay(text);
	if (!cleaned.trim()) {
		return null;
	}
	return (
		<div className={cn('xy-prose-mark', className)}>
			<span className="xy-prose-dot" aria-hidden />
			<div
				className={cn(
					'xy-chat-text min-w-0 flex-1 font-sans text-[15px] leading-relaxed text-ink',
					!isFinal && 'xy-stream-md',
				)}
			>
				<XyStreamdown
					content={cleaned}
					streaming={!isFinal}
					lite={!isFinal}
					codeAutoCollapse={codeAutoCollapse}
				/>
			</div>
		</div>
	);
});
