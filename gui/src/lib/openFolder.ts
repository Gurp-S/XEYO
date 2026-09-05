import {isTauri} from '@/lib/tauri';

/**
 * 打开文件夹选择器。
 * Tauri：原生目录对话框。浏览器：提示输入绝对路径。
 */
export async function pickFolder(title = '打开文件夹'): Promise<string | null> {
	if (isTauri()) {
		const {open} = await import('@tauri-apps/plugin-dialog');
		const selected = await open({
			directory: true,
			multiple: false,
			title,
		});
		if (typeof selected === 'string' && selected.trim()) {
			return selected.trim();
		}
		return null;
	}

	const typed = window.prompt(
		'输入要打开的文件夹绝对路径（浏览器模式无原生选夹）',
		'',
	);
	if (typed === null) {
		return null;
	}
	const path = typed.trim();
	return path || null;
}
