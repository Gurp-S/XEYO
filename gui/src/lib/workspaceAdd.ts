import {pickFolder} from '@/lib/openFolder';
import {folderName, joinFsPath} from '@/lib/paths';
import {isTauri} from '@/lib/tauri';

const FOLDER_NAME_RE = /^[^<>:"/\\|?*]+$/;

export function isValidFolderName(name: string): boolean {
	const n = name.trim();
	if (!n || n === '.' || n === '..') {
		return false;
	}
	if (n.endsWith('.') || n.endsWith(' ')) {
		return false;
	}
	return FOLDER_NAME_RE.test(n);
}

/** `owner/repo` → GitHub HTTPS；已是 URL 则原样返回。 */
export function expandGitUrl(input: string): string | null {
	const t = input.trim();
	if (!t) {
		return null;
	}
	if (/^(https?:\/\/|git@)/i.test(t)) {
		return t;
	}
	if (/^[\w.-]+\/[\w.-]+$/.test(t)) {
		return `https://github.com/${t}.git`;
	}
	return null;
}

export function repoNameFromGitUrl(url: string): string | null {
	const t = url.trim().replace(/\.git$/i, '');
	const github = t.match(/(?:github\.com[:/]|gitlab\.com[:/])([^/]+)\/([^/#?]+)/i);
	if (github?.[2]) {
		return github[2];
	}
	const parts = t.split(/[/\\]/).filter(Boolean);
	const last = parts[parts.length - 1];
	if (!last || last.includes(':') || last.includes('@')) {
		return null;
	}
	return last;
}

async function invokeFs<T>(cmd: string, args: Record<string, unknown>): Promise<T> {
	if (!isTauri()) {
		throw new Error('此操作需要桌面端');
	}
	const {invoke} = await import('@tauri-apps/api/core');
	return invoke<T>(cmd, args);
}

export async function createDirectory(path: string): Promise<void> {
	await invokeFs('create_directory', {path});
}

export async function gitInit(path: string): Promise<void> {
	await invokeFs('git_init', {path});
}

export async function gitClone(url: string, dest: string): Promise<void> {
	await invokeFs('git_clone', {url, dest});
}

export async function listGitRepos(roots: string[]): Promise<string[]> {
	if (!isTauri() || roots.length === 0) {
		return [];
	}
	try {
		return await invokeFs<string[]>('list_git_repos', {roots});
	} catch {
		return [];
	}
}

export async function pickNewFolderPath(
	title: string,
	nameTitle: string,
	placeholder: string,
): Promise<string | null> {
	const parent = await pickFolder(title);
	if (!parent) {
		return null;
	}
	const {promptDialog} = await import('@/lib/inlineDialog');
	const name = await promptDialog({
		title: nameTitle,
		placeholder,
	});
	if (!name) {
		return null;
	}
	if (!isValidFolderName(name)) {
		throw new Error('文件夹名称无效');
	}
	return joinFsPath(parent, name);
}

export async function createEmptyProject(path: string): Promise<void> {
	await createDirectory(path);
	try {
		await gitInit(path);
	} catch {
		/* 无 git 时仍作为空文件夹打开 */
	}
}

export function cloneDestPath(parent: string, url: string): string {
	const name = repoNameFromGitUrl(url) || folderName(url) || 'repo';
	if (!isValidFolderName(name)) {
		throw new Error('无法从仓库 URL 解析文件夹名');
	}
	return joinFsPath(parent, name);
}
