import {gitStatus, type GitStatusResult} from '@/lib/api';

// Share only pending reads. A refresh always gets a new snapshot after settlement.
const pending = new Map<string, Promise<GitStatusResult>>();
export function readWorkspaceGit(root: string): Promise<GitStatusResult> {
	const current = pending.get(root);
	if (current) return current;
	const read = gitStatus(root).then(result => {
		if (!result.ok) throw new Error('Git 状态读取失败');
		return result;
	}).finally(() => { if (pending.get(root) === read) pending.delete(root); });
	pending.set(root, read);
	return read;
}

export function workspaceGitFiles(status: GitStatusResult | null) {
	const files = new Map<string, {path:string;name:string;add:number;del:number;gitStatus:string}>();
	for (const [group, entries] of [['staged',status?.staged],['unstaged',status?.unstaged],['untracked',status?.untracked]] as const) {
		for (const entry of entries ?? []) {
			const symbol = group === 'untracked' ? '?' : entry.status.trim() || 'M';
			const previous = files.get(entry.path);
			const codes = new Set([...(previous?.gitStatus.split(' / ') ?? []),symbol]);
			files.set(entry.path, {path:entry.path,name:entry.path.replace(/\\/g,'/').split('/').at(-1) ?? entry.path,add:0,del:0,gitStatus:[...codes].join(' / ')});
		}
	}
	return [...files.values()];
}
