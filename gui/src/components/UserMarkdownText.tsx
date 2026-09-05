import {memo} from 'react';
import {looksLikeMarkdown} from '@/lib/chatMarkdown';
import {cn} from '@/lib/utils';
import {MarkdownView} from './MarkdownView';

type Props = {
	text: string;
	className?: string;
};

/**
 * 用户输入文本的统一渲染出口（历史气泡 / sticky 气泡 / MessageBubble 回退）。
 *
 * 看起来是 Markdown（块级 / 行内语法探测，同流式口径）→ 走 MarkdownView
 * （lite：跳过 mermaid/KaTeX；breaks：单换行渲染为 <br>，聊天口径）；
 * 否则维持 whitespace-pre-wrap 原文渲染，普通消息零变化。
 */
export const UserMarkdownText = memo(function UserMarkdownText({
	text,
	className,
}: Props) {
	if (!looksLikeMarkdown(text)) {
		return <div className={cn(className, 'whitespace-pre-wrap')}>{text}</div>;
	}
	return (
		<MarkdownView
			content={text}
			className={className}
			lite
			breaks
		/>
	);
});
