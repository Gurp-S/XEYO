/** Archify 泳道式架构布局 + Understand-Anything 风格代码节点。纯函数，无 DOM。 */

export const LAYER_ORDER = [
	'ui',
	'api',
	'engine',
	'tools',
	'prompt',
	'memory',
	'policy',
	'core',
	'test',
	'docs',
	// 本轮工作流泳道
	'agent',
	'read',
	'write',
	'search',
	'command',
	'other',
	'files',
] as const;

export const LAYER_LABELS: Record<string, string> = {
	ui: 'UI',
	api: 'API',
	engine: '引擎',
	tools: '工具',
	prompt: '提示',
	memory: '记忆',
	policy: '权限',
	core: '核心',
	test: '测试',
	docs: '文档',
	agent: 'Agent',
	read: '读',
	write: '改',
	search: '搜',
	command: '命令',
	other: '其他',
	files: '文件',
};

export type GraphFile = {
	id: string;
	name: string;
	layer: string;
	pkg: string;
};

export type GraphPackage = {
	id: string;
	name: string;
	layer: string;
	files: number;
};

export type GraphEdge = {from: string; to: string};

export type LaidNode = {
	id: string;
	name: string;
	layer: string;
	kind: 'file' | 'package' | 'step' | 'symbol' | 'authored';
	x: number;
	y: number;
	w: number;
	h: number;
	files?: number;
};

export type LaidEdge = {
	from: string;
	to: string;
	x1: number;
	y1: number;
	x2: number;
	y2: number;
};

/** 同层功能区背景（UE 蓝图 comment 框）。 */
export type LaidLane = {
	layer: string;
	x: number;
	y: number;
	w: number;
	h: number;
};

export type LaneLayout = {
	nodes: LaidNode[];
	edges: LaidEdge[];
	lanes: LaidLane[];
	width: number;
	height: number;
};

const CHIP_H = 40;
const CHIP_W = 140;
const GAP_X = 12;
const GAP_Y = 12;
const LANE_HEAD = 26;
const LANE_INSET = 10;
const LANE_GAP = 16;
const PAD = 16;
/** 单列最多叠多少节点，再多就加内列，避免整图竖成一条。 */
const MAX_STACK = 8;
/** 代码视图节点硬顶（含落点一跳邻居），防超大仓 DOM/SVG 卡死。 */
export const CODE_VIEW_FILE_CAP = 64;
/** 本轮步骤硬顶（保留最近）。 */
export const TURN_STEP_CAP = 48;

export function fitLabel(text: string, maxUnits: number): string {
	const raw = text.trim();
	if (!raw || maxUnits < 2) {
		return raw;
	}
	let units = 0;
	let end = 0;
	for (; end < raw.length; end += 1) {
		const w = raw.charCodeAt(end) > 0xff ? 2 : 1;
		if (units + w > maxUnits) {
			break;
		}
		units += w;
	}
	if (end >= raw.length) {
		return raw;
	}
	while (end > 0 && units > maxUnits - 1) {
		end -= 1;
		units -= raw.charCodeAt(end) > 0xff ? 2 : 1;
	}
	return `${raw.slice(0, Math.max(1, end))}…`;
}

function layerRank(layer: string): number {
	const i = (LAYER_ORDER as readonly string[]).indexOf(layer);
	return i >= 0 ? i : LAYER_ORDER.length;
}

function innerColsFor(count: number): number {
	if (count <= MAX_STACK) {
		return 1;
	}
	return Math.min(3, Math.ceil(count / MAX_STACK));
}

/**
 * 横向泳道：每层一列（左→右），层内节点上→下；节点多时层内再分列。
 * laneWidth 仅作最小画布宽提示，实际宽度随层数生长。
 */
export function layoutLanes(
	items: Array<{
		id: string;
		name: string;
		layer: string;
		files?: number;
		kind?: LaidNode['kind'];
	}>,
	edges: GraphEdge[],
	kind: LaidNode['kind'],
	laneWidth: number,
): LaneLayout {
	const grouped = new Map<string, typeof items>();
	for (const item of items) {
		const layer = item.layer || 'core';
		const list = grouped.get(layer) ?? [];
		list.push(item);
		grouped.set(layer, list);
	}
	const layers = [...grouped.keys()].sort((a, b) => layerRank(a) - layerRank(b));
	const nodes: LaidNode[] = [];
	const lanes: LaidLane[] = [];
	let x = PAD;
	let maxBandH = 0;

	for (const layer of layers) {
		const list = grouped.get(layer) ?? [];
		const innerCols = innerColsFor(list.length);
		const rows = Math.max(1, Math.ceil(list.length / innerCols));
		const bandW = LANE_INSET * 2 + innerCols * CHIP_W + (innerCols - 1) * GAP_X;
		const contentTop = PAD + LANE_HEAD + LANE_INSET;
		list.forEach((item, i) => {
			const col = i % innerCols;
			const row = Math.floor(i / innerCols);
			nodes.push({
				id: item.id,
				name: item.name,
				layer,
				kind: item.kind ?? kind,
				x: x + LANE_INSET + col * (CHIP_W + GAP_X),
				y: contentTop + row * (CHIP_H + GAP_Y),
				w: CHIP_W,
				h: CHIP_H,
				...(item.files != null ? {files: item.files} : {}),
			});
		});
		const contentH = rows * (CHIP_H + GAP_Y) - GAP_Y;
		const bandH = LANE_HEAD + LANE_INSET + Math.max(contentH, CHIP_H) + LANE_INSET;
		lanes.push({
			layer,
			x,
			y: PAD,
			w: bandW,
			h: bandH,
		});
		maxBandH = Math.max(maxBandH, bandH);
		x += bandW + LANE_GAP;
	}

	// 同高对齐列，预览更整齐
	for (const lane of lanes) {
		lane.h = maxBandH;
	}

	const byId = new Map(nodes.map(n => [n.id, n]));
	const laidEdges: LaidEdge[] = [];
	for (const edge of edges) {
		const a = byId.get(edge.from);
		const b = byId.get(edge.to);
		if (!a || !b) {
			continue;
		}
		laidEdges.push({
			from: edge.from,
			to: edge.to,
			x1: a.x + a.w / 2,
			y1: a.y + a.h / 2,
			x2: b.x + b.w / 2,
			y2: b.y + b.h / 2,
		});
	}

	const width = Math.max(
		laneWidth,
		layers.length ? x - LANE_GAP + PAD : PAD * 2 + 120,
	);
	return {
		nodes,
		edges: laidEdges,
		lanes,
		width,
		height: Math.max(PAD + maxBandH + PAD, 140),
	};
}

export function filterGraph(
	items: Array<{id: string; name: string; layer: string; files?: number}>,
	query: string,
): typeof items {
	const q = query.trim().toLowerCase();
	if (!q) {
		return items;
	}
	return items.filter(
		item =>
			item.id.toLowerCase().includes(q) ||
			item.name.toLowerCase().includes(q) ||
			item.layer.toLowerCase().includes(q),
	);
}

/** 路径宽松匹配：精确 / 互为后缀（应对 cwd 相对差异）。 */
export function pathsLooselyEqual(a: string, b: string): boolean {
	const x = a.replace(/\\/g, '/').replace(/^\.\//, '').toLowerCase();
	const y = b.replace(/\\/g, '/').replace(/^\.\//, '').toLowerCase();
	if (!x || !y) {
		return false;
	}
	return x === y || x.endsWith(`/${y}`) || y.endsWith(`/${x}`);
}

/** 代码视图：有落点时只展示命中文件及其一跳邻居，避免整仓头发球。 */
export function focusFiles(
	files: GraphFile[],
	fileEdges: GraphEdge[],
	focusIds: string[],
	limit = CODE_VIEW_FILE_CAP,
): {files: GraphFile[]; edges: GraphEdge[]} {
	if (!focusIds.length) {
		const head = files.slice(0, limit);
		const ids = new Set(head.map(f => f.id));
		return {
			files: head,
			edges: fileEdges.filter(e => ids.has(e.from) && ids.has(e.to)),
		};
	}
	const seed = new Set<string>();
	for (const f of files) {
		if (focusIds.some(id => pathsLooselyEqual(f.id, id))) {
			seed.add(f.id);
		}
	}
	const wanted = new Set(seed);
	for (const edge of fileEdges) {
		if (wanted.has(edge.from)) {
			wanted.add(edge.to);
		}
		if (wanted.has(edge.to)) {
			wanted.add(edge.from);
		}
	}
	// 种子优先排前，便于镜头与 ops 跳转
	const picked = [
		...files.filter(f => seed.has(f.id)),
		...files.filter(f => wanted.has(f.id) && !seed.has(f.id)),
	].slice(0, limit);
	const ids = new Set(picked.map(f => f.id));
	return {
		files: picked,
		edges: fileEdges.filter(e => ids.has(e.from) && ids.has(e.to)),
	};
}
