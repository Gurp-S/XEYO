import {isTauri} from '@/lib/tauri';

/**
 * 把用户显式选择过的目录登记为允许写入的根。
 * 这是信任边界：路径来自系统选夹对话框（或已保存的工作区记录），
 * 后端据此判定后续 fs/git 操作是否越界。失败静默——登记不上时后续操作会自行报错。
 */
export async function registerAllowedRoots(roots: string[]): Promise<void> {
	if (!isTauri() || roots.length === 0) {
		return;
	}
	try {
		const {invoke} = await import('@tauri-apps/api/core');
		await invoke('set_allowed_roots', {roots});
	} catch {
		/* 登记失败不阻断 UI；写操作届时会给出越界提示 */
	}
}

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
			const picked = selected.trim();
			// 用户当场选定即授权（含其子目录）
			await registerAllowedRoots([picked]);
			return picked;
		}
		return null;
	}

	// 原生 window.prompt 阻塞主线程、样式与应用浮层脱节；改用统一弹窗。
	const {promptDialog} = await import('@/lib/inlineDialog');
	const typed = await promptDialog({
		title: '输入要打开的文件夹绝对路径（浏览器模式无原生选夹）',
		placeholder: '例如 D:\\project',
	});
	if (typed === null) {
		return null;
	}
	const path = typed.trim();
	return path || null;
}
