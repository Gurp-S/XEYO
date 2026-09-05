/** 解析 agent 撰写的 ```xeyo-map 图稿 JSON。 */

import type {AuthoredMapDoc} from '@/stores/codeMapStore';

const KINDS = new Set([
	'architecture',
	'workflow',
	'sequence',
	'dataflow',
	'lifecycle',
]);

export function parseXeyoMapFence(source: string): AuthoredMapDoc | null {
	const raw = source.trim();
	if (!raw) {
		return null;
	}
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return null;
	}
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return null;
	}
	const obj = parsed as Record<string, unknown>;
	const kind = String(obj.kind || '').trim().toLowerCase();
	if (!KINDS.has(kind)) {
		return null;
	}
	const nodesRaw = obj.nodes;
	const edgesRaw = obj.edges;
	if (!Array.isArray(nodesRaw) || !Array.isArray(edgesRaw)) {
		return null;
	}
	const nodes: AuthoredMapDoc['nodes'] = [];
	for (const n of nodesRaw) {
		if (!n || typeof n !== 'object') {
			continue;
		}
		const row = n as Record<string, unknown>;
		const id = String(row.id || '').trim();
		const label = String(row.label || row.name || id).trim();
		if (!id || !label) {
			continue;
		}
		nodes.push({
			id,
			label,
			...(typeof row.lane === 'string' && row.lane.trim()
				? {lane: row.lane.trim()}
				: {}),
			...(typeof row.file === 'string' && row.file.trim()
				? {file: row.file.trim().replace(/\\/g, '/')}
				: {}),
		});
	}
	const edges: AuthoredMapDoc['edges'] = [];
	for (const e of edgesRaw) {
		if (!e || typeof e !== 'object') {
			continue;
		}
		const row = e as Record<string, unknown>;
		const from = String(row.from || '').trim();
		const to = String(row.to || '').trim();
		if (!from || !to) {
			continue;
		}
		edges.push({
			from,
			to,
			...(typeof row.label === 'string' && row.label.trim()
				? {label: row.label.trim()}
				: {}),
		});
	}
	if (!nodes.length) {
		return null;
	}
	return {
		kind: kind as AuthoredMapDoc['kind'],
		...(typeof obj.title === 'string' && obj.title.trim()
			? {title: obj.title.trim()}
			: {}),
		nodes,
		edges,
	};
}
