import {readWorkspaceFile} from '@/lib/api';
import {isTauri} from '@/lib/tauri';
import {toast} from '@/lib/toast';
import {useChatStore} from '@/stores/chatStore';

/** 拼接工作区根路径与相对 entry 路径。 */
export function joinWorkspacePath(rootPath: string, entryPath: string): string {
	if (!rootPath) {
		return entryPath;
	}
	if (/^(?:[a-zA-Z]:[\\/]|[\\/]{2})/.test(entryPath) || entryPath.startsWith('/')) {
		return entryPath;
	}
	const root = rootPath.replace(/[\\/]+$/, '');
	const child = entryPath.replace(/^[\\/]+/, '');
	return `${root}${root.includes('\\') ? '\\' : '/'}${child}`;
}

async function withToast(action: () => Promise<void>): Promise<void> {
	try {
		await action();
	} catch (err) {
		toast.error(err instanceof Error ? err.message : String(err));
	}
}

/** 剪贴板写入：优先 Clipboard API，失败则回退 execCommand（Tauri webview 更稳）。 */
async function writeClipboard(text: string): Promise<void> {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return;
		}
	} catch {
		/* 继续向下执行 */
	}
	const ta = document.createElement('textarea');
	ta.value = text;
	ta.setAttribute('readonly', '');
	ta.style.position = 'fixed';
	ta.style.left = '-9999px';
	document.body.appendChild(ta);
	ta.select();
	const ok = document.execCommand('copy');
	document.body.removeChild(ta);
	if (!ok) {
		throw new Error('当前环境不支持复制');
	}
}

export async function openInVsCode(absolutePath: string): Promise<void> {
	await withToast(async () => {
		if (!absolutePath.trim()) {
			throw new Error('路径无效');
		}
		// vscode://file/<abs> — 保留盘符冒号，只统一分隔符
		const path = absolutePath.replace(/\\/g, '/');
		const uri = `vscode://file/${path}`;
		if (isTauri()) {
			const {open} = await import('@tauri-apps/plugin-shell');
			await open(uri);
			return;
		}
		window.open(uri, '_blank', 'noopener,noreferrer');
	});
}

export async function openWithDefaultApp(absolutePath: string): Promise<void> {
	await withToast(async () => {
		if (!absolutePath.trim()) {
			throw new Error('路径无效');
		}
		if (isTauri()) {
			const {open} = await import('@tauri-apps/plugin-shell');
			await open(absolutePath);
			return;
		}
		toast.info('浏览器模式无法用系统程序打开本地文件');
	});
}

/** 在系统文件管理器中定位并选中路径。 */
export async function revealInFolder(absolutePath: string): Promise<void> {
	await withToast(async () => {
		if (!absolutePath.trim()) {
			throw new Error('路径无效');
		}
		if (isTauri()) {
			const {invoke} = await import('@tauri-apps/api/core');
			await invoke('reveal_in_folder', {path: absolutePath});
			return;
		}
		toast.info('浏览器模式无法打开系统资源管理器');
	});
}

export async function saveWorkspaceFileAs(
	entryPath: string,
	entryName: string,
): Promise<void> {
	await withToast(async () => {
		const file = await readWorkspaceFile(entryPath);
		if (file.text == null) {
			throw new Error('该文件无法作为文本另存为');
		}
		const name = file.name || entryName;
		if (!isTauri()) {
			const blob = new Blob([file.text], {type: 'text/plain;charset=utf-8'});
			const url = URL.createObjectURL(blob);
			const anchor = document.createElement('a');
			anchor.href = url;
			anchor.download = name;
			anchor.click();
			URL.revokeObjectURL(url);
			return;
		}
		const {save} = await import('@tauri-apps/plugin-dialog');
		const destination = await save({
			defaultPath: name,
			filters: [{name: '文本文件', extensions: ['*']}],
		});
		if (destination) {
			const {invoke} = await import('@tauri-apps/api/core');
			await invoke('save_text_file', {path: destination, text: file.text});
		}
	});
}

export async function copyPathToClipboard(absolutePath: string): Promise<void> {
	await withToast(async () => {
		if (!absolutePath.trim()) {
			throw new Error('路径无效');
		}
		await writeClipboard(absolutePath);
		toast.success('已复制路径');
	});
}

export async function copyRelativePathToClipboard(
	relativePath: string,
): Promise<void> {
	await withToast(async () => {
		await writeClipboard(relativePath.replace(/\\/g, '/'));
		toast.success('已复制相对路径');
	});
}

export async function addWorkspaceFileToChat(
	entryPath: string,
	entryName: string,
): Promise<void> {
	await withToast(async () => {
		const path = entryPath.trim();
		const name = entryName.trim() || path.split(/[\\/]/).pop() || 'file';
		if (!path) {
			throw new Error('路径无效');
		}
		// 只挂文件引用，不读全文进输入框（大文件会撑爆 GUI）
		useChatStore.getState().requestComposerInsert({name, path});
	});
}

export async function copyTextToClipboard(
	text: string,
	okMsg = '已复制',
): Promise<void> {
	await withToast(async () => {
		await writeClipboard(text);
		toast.success(okMsg);
	});
}

export async function readClipboardText(): Promise<string> {
	if (navigator.clipboard?.readText) {
		try {
			return await navigator.clipboard.readText();
		} catch {
			/* 继续向下执行 */
		}
	}
	throw new Error('当前环境不支持粘贴');
}
