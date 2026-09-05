import type {ContextMenuItem} from '@/stores/contextMenuStore';
import type {WorkspaceEntry} from '@/lib/api';
import {
	addWorkspaceFileToChat,
	copyPathToClipboard,
	copyRelativePathToClipboard,
	copyTextToClipboard,
	openInVsCode,
	openWithDefaultApp,
	readClipboardText,
	revealInFolder,
	saveWorkspaceFileAs,
} from '@/lib/workspaceOpen';

/** Cursor 风格：输入框 Cut / Copy / Paste / Select All（无图标，紧凑）。 */
export function textFieldMenuItems(
	el: HTMLTextAreaElement | HTMLInputElement,
): ContextMenuItem[] {
	const start = el.selectionStart ?? 0;
	const end = el.selectionEnd ?? 0;
	const hasSelection = end > start;
	const value = el.value;

	const replaceSelection = (next: string) => {
		const before = value.slice(0, start);
		const after = value.slice(end);
		const merged = `${before}${next}${after}`;
		const proto = Object.getOwnPropertyDescriptor(
			el instanceof HTMLTextAreaElement
				? HTMLTextAreaElement.prototype
				: HTMLInputElement.prototype,
			'value',
		);
		proto?.set?.call(el, merged);
		el.dispatchEvent(new Event('input', {bubbles: true}));
		const caret = before.length + next.length;
		el.setSelectionRange(caret, caret);
		el.focus();
	};

	return [
		{
			kind: 'action',
			id: 'cut',
			label: '剪切',
			shortcut: 'Ctrl+X',
			disabled: !hasSelection || el.readOnly || el.disabled,
			onSelect: () => {
				const selected = value.slice(start, end);
				void copyTextToClipboard(selected, '已剪切').then(() => {
					replaceSelection('');
				});
			},
		},
		{
			kind: 'action',
			id: 'copy',
			label: '复制',
			shortcut: 'Ctrl+C',
			disabled: !hasSelection,
			onSelect: () => void copyTextToClipboard(value.slice(start, end)),
		},
		{
			kind: 'action',
			id: 'paste',
			label: '粘贴',
			shortcut: 'Ctrl+V',
			disabled: el.readOnly || el.disabled,
			onSelect: () => {
				void (async () => {
					try {
						replaceSelection(await readClipboardText());
					} catch (err) {
						const {toast} = await import('@/lib/toast');
						toast.error(err instanceof Error ? err.message : String(err));
					}
				})();
			},
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'select-all',
			label: '全选',
			shortcut: 'Ctrl+A',
			disabled: value.length === 0,
			onSelect: () => {
				el.focus();
				el.setSelectionRange(0, value.length);
			},
		},
	];
}

/** 文件树 / 变更行：精简条目，无图标。 */
export function filePathMenuItems(opts: {
	entryPath: string;
	entryName: string;
	absolutePath: string;
	kind?: WorkspaceEntry['kind'] | 'file' | 'dir';
	onOpen?: () => void;
	onOpenReview?: () => void;
	includeAddToChat?: boolean;
	includeSaveAs?: boolean;
}): ContextMenuItem[] {
	const kind = opts.kind ?? 'file';
	const fileOnly = kind !== 'file';
	const items: ContextMenuItem[] = [];

	if (opts.onOpen) {
		items.push({
			kind: 'action',
			id: 'open',
			label: '打开',
			onSelect: () => opts.onOpen?.(),
		});
	}
	if (opts.onOpenReview) {
		items.push({
			kind: 'action',
			id: 'open-review',
			label: '查看 Diff',
			onSelect: () => opts.onOpenReview?.(),
		});
	}

	items.push(
		{
			kind: 'action',
			id: 'open-vscode',
			label: '在 VS Code 中打开',
			onSelect: () => void openInVsCode(opts.absolutePath),
		},
		{
			kind: 'action',
			id: 'open-default',
			label: '用系统默认程序打开',
			onSelect: () => void openWithDefaultApp(opts.absolutePath),
		},
		{
			kind: 'action',
			id: 'reveal',
			label: '在资源管理器中显示',
			onSelect: () => void revealInFolder(opts.absolutePath),
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'copy-path',
			label: '复制路径',
			onSelect: () => void copyPathToClipboard(opts.absolutePath),
		},
		{
			kind: 'action',
			id: 'copy-rel',
			label: '复制相对路径',
			onSelect: () => void copyRelativePathToClipboard(opts.entryPath),
		},
	);

	if (opts.includeSaveAs !== false && !fileOnly) {
		items.push({
			kind: 'action',
			id: 'save-as',
			label: '另存为…',
			onSelect: () => void saveWorkspaceFileAs(opts.entryPath, opts.entryName),
		});
	}

	if (opts.includeAddToChat !== false && !fileOnly) {
		items.push({
			kind: 'action',
			id: 'add-to-chat',
			label: '添加到聊天',
			onSelect: () =>
				void addWorkspaceFileToChat(opts.entryPath, opts.entryName),
		});
	}

	return items;
}

export function sessionMenuItems(opts: {
	sessionId: string;
	title: string;
	onDelete: () => void;
}): ContextMenuItem[] {
	return [
		{
			kind: 'action',
			id: 'copy-id',
			label: '复制会话 ID',
			onSelect: () => void copyTextToClipboard(opts.sessionId, '已复制会话 ID'),
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'delete',
			label: '删除会话',
			danger: true,
			onSelect: opts.onDelete,
		},
	];
}

export function userMessageMenuItems(opts: {
	text: string;
	canEdit: boolean;
	onEdit?: () => void;
}): ContextMenuItem[] {
	const items: ContextMenuItem[] = [
		{
			kind: 'action',
			id: 'copy',
			label: '复制',
			onSelect: () => void copyTextToClipboard(opts.text),
		},
	];
	if (opts.canEdit) {
		items.push({
			kind: 'action',
			id: 'edit',
			label: '编辑消息',
			onSelect: () => opts.onEdit?.(),
		});
	}
	return items;
}

export function assistantCopyMenuItems(markdown: string): ContextMenuItem[] {
	const plain = markdown.replace(/```[\s\S]*?```/g, block => {
		const lines = block.split('\n');
		return lines.slice(1, -1).join('\n');
	});
	return [
		{
			kind: 'action',
			id: 'copy-md',
			label: '复制',
			onSelect: () => void copyTextToClipboard(markdown),
		},
		{
			kind: 'action',
			id: 'copy-plain',
			label: '复制纯文本',
			onSelect: () => void copyTextToClipboard(plain || markdown),
		},
	];
}

export function codeBlockMenuItems(code: string, language?: string): ContextMenuItem[] {
	return [
		{
			kind: 'action',
			id: 'copy',
			label: '复制',
			onSelect: () => void copyTextToClipboard(code),
		},
		{
			kind: 'action',
			id: 'copy-fence',
			label: '复制为 Markdown',
			onSelect: () => {
				const lang = (language || '').trim();
				void copyTextToClipboard(`\`\`\`${lang}\n${code}\n\`\`\``);
			},
		},
	];
}

export function toolStepMenuItems(opts: {
	preview: string;
	detail?: string;
	result?: string;
}): ContextMenuItem[] {
	const items: ContextMenuItem[] = [
		{
			kind: 'action',
			id: 'copy-preview',
			label: '复制命令',
			onSelect: () =>
				void copyTextToClipboard(opts.detail?.trim() || opts.preview),
		},
	];
	if (opts.result?.trim()) {
		items.push({
			kind: 'action',
			id: 'copy-result',
			label: '复制输出',
			onSelect: () => void copyTextToClipboard(opts.result!),
		});
	}
	return items;
}
