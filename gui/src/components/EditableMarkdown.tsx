import {
	forwardRef,
	useCallback,
	useEffect,
	useImperativeHandle,
	useLayoutEffect,
	useRef,
	useState,
} from 'react';
import {MarkdownView} from '@/components/MarkdownView';
import {htmlToMarkdown} from '@/lib/htmlToMarkdown';

export type EditableMarkdownHandle = {
	flush: () => string;
};

type Props = {
	content: string;
	onChange: (md: string) => void;
	onSave?: () => void;
	className?: string;
	codeAutoCollapse?: boolean;
	basePath?: string;
	onOpenPath?: (path: string, hash?: string) => void;
	scrollToId?: string | null;
	/** 递增后强制按 content 重渲染（格式化工具条写回源码后）。 */
	revision?: number;
};

function lockChrome(root: HTMLElement) {
	root
		.querySelectorAll(
			'.katex, .katex-display, img, button, input, .xy-code-surface, .xy-code-file',
		)
		.forEach(node => {
			if (node instanceof HTMLElement) {
				node.contentEditable = 'false';
			}
		});
}

function insertPlain(text: string) {
	try {
		document.execCommand('insertText', false, text);
	} catch {
		const sel = window.getSelection();
		if (!sel || sel.rangeCount === 0) {
			return;
		}
		const range = sel.getRangeAt(0);
		range.deleteContents();
		range.insertNode(document.createTextNode(text));
		range.collapse(false);
	}
}

export const EditableMarkdown = forwardRef<EditableMarkdownHandle, Props>(
	function EditableMarkdown(
		{
			content,
			onChange,
			onSave,
			className,
			codeAutoCollapse,
			basePath,
			onOpenPath,
			scrollToId,
			revision = 0,
		},
		ref,
	) {
		const hostRef = useRef<HTMLDivElement | null>(null);
		const onChangeRef = useRef(onChange);
		onChangeRef.current = onChange;
		const contentRef = useRef(content);
		contentRef.current = content;
		const touchedRef = useRef(false);
		const [frozen, setFrozen] = useState<string | null>(null);
		const debounceRef = useRef<number>(0);
		const editVersionRef = useRef(0);
		const viewContent = frozen ?? content;

	const flush = useCallback(() => {
			window.clearTimeout(debounceRef.current);
			editVersionRef.current += 1;
			const host = hostRef.current;
			if (!host || !touchedRef.current) {
				return contentRef.current;
			}
			try {
				const md = htmlToMarkdown(host);
				if (!md && contentRef.current) {
					touchedRef.current = false;
					return contentRef.current;
				}
				touchedRef.current = false;
				onChangeRef.current(md);
				return md;
			} catch {
				touchedRef.current = false;
				return contentRef.current;
			}
		}, []);

		useImperativeHandle(ref, () => ({flush}), [flush]);

		useEffect(() => {
			return () => {
				editVersionRef.current += 1;
				window.clearTimeout(debounceRef.current);
			};
		}, []);

		useEffect(() => {
			editVersionRef.current += 1;
			window.clearTimeout(debounceRef.current);
			touchedRef.current = false;
			const host = hostRef.current;
			const focused = Boolean(
				host &&
					(document.activeElement === host ||
						host.contains(document.activeElement)),
			);
			setFrozen(focused ? contentRef.current : null);
		}, [revision]);

		useLayoutEffect(() => {
			if (hostRef.current) {
				lockChrome(hostRef.current);
			}
		}, [viewContent, revision]);

		const queueFlush = useCallback(() => {
			touchedRef.current = true;
			window.clearTimeout(debounceRef.current);
			const version = editVersionRef.current;
			debounceRef.current = window.setTimeout(() => {
				if (version !== editVersionRef.current) {
					return;
				}
				const host = hostRef.current;
				if (!host || !touchedRef.current) {
					return;
				}
				try {
					const md = htmlToMarkdown(host);
					if (!md && contentRef.current) {
						return;
					}
				onChangeRef.current(md);
				touchedRef.current = false;
			} catch {
					/* 保留上一份源码，避免把界面写坏 */
				}
			}, 220);
		}, []);

		return (
			<div
				ref={hostRef}
				role="textbox"
				aria-multiline="true"
				aria-label="Markdown 预览编辑"
				spellCheck
				contentEditable
				suppressContentEditableWarning
				className="xy-md-editable outline-none"
				onFocus={() => {
					setFrozen(current => current ?? contentRef.current);
				}}
				onInput={queueFlush}
				onChangeCapture={queueFlush}
				onBlur={e => {
					const next = e.relatedTarget as HTMLElement | null;
					if (next?.closest?.('[role="toolbar"]')) {
						return;
					}
					flush();
					setFrozen(null);
				}}
				onPaste={e => {
					e.preventDefault();
					insertPlain(e.clipboardData.getData('text/plain'));
				}}
				onKeyDown={e => {
					if (e.key === 'Tab') {
						e.preventDefault();
						insertPlain('  ');
						queueFlush();
						return;
					}
					if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
						e.preventDefault();
						flush();
						onSave?.();
					}
				}}
			>
				<MarkdownView
					content={viewContent}
					className={className}
					codeAutoCollapse={codeAutoCollapse}
					basePath={basePath}
					onOpenPath={onOpenPath}
					scrollToId={scrollToId}
					editable
				/>
			</div>
		);
	},
);
