import {memo, useEffect, useMemo, useState} from 'react';
import {perfTrace} from '@/lib/perfTrace';
import {
	prepareStaticMarkdown,
	promoteDisplayMath,
	sanitizeMarkdown,
} from '@/lib/markdownStaticCache';
import {XyStreamdown} from './XyStreamdown';
import {ImageReaderDialog, type ImageReaderSource} from './ImageReader';

// 规范实现移至 markdownStaticCache（含记忆化）；此处 re-export 兼容既有导入。
export {sanitizeMarkdown, promoteDisplayMath};

type Props = {
	content: string;
	className?: string;
	/** 为 false 时代码块保持展开（流式时使用）。默认 true。 */
	codeAutoCollapse?: boolean;
	/** 当前文件的工作区相对路径，用于解析 ./09-xxx.md */
	basePath?: string;
	/** 打开本地链接；默认走文件预览 */
	onOpenPath?: (path: string, hash?: string) => void;
	/** 打开后滚到标题 id */
	scrollToId?: string | null;
	/** 文件预览内编辑：给代码/图/公式打上来源，避免 contenteditable 改坏。 */
	editable?: boolean;
	/** 流式：跳过 mermaid/KaTeX，避免半成品图表把正文撑跳。 */
	lite?: boolean;
	/** 聊天口径：段落内单换行渲染为 <br>。 */
	breaks?: boolean;
};

/** 无 `$` 时跳过 math；`$$` 也含 `$`。 */
export function markdownHasMath(content: string): boolean {
	return content.includes('$');
}

function scrollToHeading(id: string) {
	document.getElementById(id)?.scrollIntoView({block: 'start', behavior: 'smooth'});
}

/**
 * 静态 / 文件预览 Markdown：同一 Streamdown 内核（static）。
 */
function MarkdownViewInner({
	content,
	className,
	codeAutoCollapse = true,
	basePath = '',
	onOpenPath,
	scrollToId,
	editable = false,
	lite = false,
	breaks = false,
}: Props) {
	// P1-①：sanitize/promote 记忆化（同 content 引用直接命中），逻辑不变。
	const safe = useMemo(
		() => perfTrace('markdown.prepare', () => prepareStaticMarkdown(content)),
		[content],
	);
	const [imagePreview, setImagePreview] = useState<ImageReaderSource | null>(null);

	useEffect(() => {
		if (!scrollToId) {
			return;
		}
		const t = window.setTimeout(() => scrollToHeading(scrollToId), 40);
		return () => window.clearTimeout(t);
	}, [safe, scrollToId]);

	return (
		<div className={className}>
			<XyStreamdown
				content={safe}
				streaming={false}
				lite={lite}
				breaks={breaks}
				codeAutoCollapse={codeAutoCollapse}
				basePath={basePath}
				onOpenPath={onOpenPath}
				editable={editable}
				onImagePreview={(src, alt) => setImagePreview({src, alt})}
			/>
			<ImageReaderDialog
				image={imagePreview}
				onClose={() => setImagePreview(null)}
			/>
		</div>
	);
}

export const MarkdownView = memo(MarkdownViewInner);
