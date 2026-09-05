import type {RollbackOperation} from '@/lib/types';

export type RollbackFileEntry = {
	path: string;
	relativePath: string;
	diff: string;
	kind: 'restore' | 'trash';
	stats: {add: number; del: number};
};

export type RollbackTreeDir = {
	type: 'dir';
	name: string;
	key: string;
	children: RollbackTreeNode[];
};

export type RollbackTreeFile = {
	type: 'file';
	name: string;
	key: string;
	entry: RollbackFileEntry;
};

export type RollbackTreeNode = RollbackTreeDir | RollbackTreeFile;

export function relativeRollbackPath(
	rawPath: string,
	workspaceRoot?: string,
): string {
	const normalized = rawPath.replace(/\\/g, '/');
	if (!workspaceRoot) {
		return normalized;
	}
	const root = workspaceRoot.replace(/\\/g, '/').replace(/\/$/, '');
	const lowerPath = normalized.toLowerCase();
	const lowerRoot = root.toLowerCase();
	if (lowerPath.startsWith(`${lowerRoot}/`)) {
		return normalized.slice(root.length + 1);
	}
	return normalized;
}

export function diffLineStats(diff: string): {add: number; del: number} {
	let add = 0;
	let del = 0;
	for (const line of diff.split('\n')) {
		if (line.startsWith('+') && !line.startsWith('+++')) {
			add += 1;
		} else if (line.startsWith('-') && !line.startsWith('---')) {
			del += 1;
		}
	}
	return {add, del};
}

export function classifyRollbackOperation(
	op: RollbackOperation,
): 'restore' | 'trash' | null {
	if (typeof op !== 'object' || op === null) {
		return null;
	}
	if ('after_hash' in op && op.after_hash !== null) {
		return 'restore';
	}
	return 'trash';
}

export function buildRollbackDiffTree(
	operations: RollbackOperation[],
	workspaceRoot?: string,
): RollbackTreeNode[] {
	const entries: RollbackFileEntry[] = [];
	for (const op of operations) {
		const kind = classifyRollbackOperation(op);
		const path = typeof op.path === 'string' ? op.path : '';
		if (!kind || !path) {
			continue;
		}
		const relativePath = relativeRollbackPath(path, workspaceRoot);
		const diff =
			typeof op.preview_diff === 'string' ? op.preview_diff.trim() : '';
		entries.push({
			path,
			relativePath,
			diff,
			kind,
			stats: diffLineStats(diff),
		});
	}
	entries.sort((a, b) => a.relativePath.localeCompare(b.relativePath));

	const root: RollbackTreeDir = {type: 'dir', name: '', key: 'root', children: []};

	for (const entry of entries) {
		const parts = entry.relativePath.split('/').filter(Boolean);
		const fileName = parts.pop() ?? entry.relativePath;
		let cursor = root;
		let keyPrefix = 'root';
		for (const part of parts) {
			keyPrefix += `/${part}`;
			let next = cursor.children.find(
				(node): node is RollbackTreeDir =>
					node.type === 'dir' && node.name === part,
			);
			if (!next) {
				next = {type: 'dir', name: part, key: keyPrefix, children: []};
				cursor.children.push(next);
			}
			cursor = next;
		}
		cursor.children.push({
			type: 'file',
			name: fileName,
			key: `${keyPrefix}/${fileName}`,
			entry,
		});
	}

	const sortNodes = (nodes: RollbackTreeNode[]): RollbackTreeNode[] =>
		nodes
			.map(node =>
				node.type === 'dir'
					? {...node, children: sortNodes(node.children)}
					: node,
			)
			.sort((a, b) => {
				if (a.type !== b.type) {
					return a.type === 'dir' ? -1 : 1;
				}
				return a.name.localeCompare(b.name);
			});

	return sortNodes(root.children);
}

export function collectRollbackTreeKeys(nodes: RollbackTreeNode[]): string[] {
	const keys: string[] = [];
	const walk = (list: RollbackTreeNode[]) => {
		for (const node of list) {
			keys.push(node.key);
			if (node.type === 'dir') {
				walk(node.children);
			}
		}
	};
	walk(nodes);
	return keys;
}
