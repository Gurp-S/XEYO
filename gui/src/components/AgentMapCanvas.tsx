import {
	memo,
	useEffect,
	useMemo,
	useRef,
	useState,
	type PointerEvent as ReactPointerEvent,
	type WheelEvent as ReactWheelEvent,
} from 'react';
import {cn} from '@/lib/utils';
import {
	LAYER_LABELS,
	LAYER_ORDER,
	fitLabel,
	layoutLanes,
	pathsLooselyEqual,
	type LaidLane,
	type LaidNode,
} from '@/lib/codeMapLayout';
import type {AgentPresenceHit} from '@/lib/agentPresence';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';

type Props = {
	nodes: LaidNode[];
	edges: Array<{
		from: string;
		to: string;
		x1: number;
		y1: number;
		x2: number;
		y2: number;
	}>;
	lanes?: LaidLane[];
	width: number;
	height: number;
	selectedId: string | null;
	/** 进行中节点 id：镜头跟随。 */
	followId?: string | null;
	/** 强制把镜头对准该节点（可带 #seq 以重复触发）。 */
	focusRequestId?: string | null;
	onSelect: (id: string, kind: LaidNode['kind']) => void;
	/** Panel 预计算：nodeId → 最新 hit（避免每节点扫 hits[]）。 */
	hitByNodeId?: Map<string, AgentPresenceHit>;
	/** 搜索命中（query ≥ 2）。 */
	searchHitIds?: Set<string>;
	/** 本轮操作轨迹（时间序），叠在依赖边之上。 */
	opsTrail?: Array<{from: string; to: string}>;
	/** 仅回放播放中开流动画；静止时只画静态轨迹+箭头。 */
	trailAnimate?: boolean;
	/** 回放当前帧路径：节点按 live 高亮。 */
	replayPath?: string | null;
	/** 回放当前帧动词（Read / Edited…）。 */
	replayVerb?: string | null;
	/** 步骤视图：用自定义 hit 判定（id 即 step id）。 */
	stepRunningIds?: Set<string>;
	stepSeenIds?: Set<string>;
	stepVerbs?: Map<string, string>;
};

const EDGE_CAP = 120;
const CAM_DEFAULT = {x: 12, y: 8, k: 1};
/** 芯片内标题/副标题视觉宽度单位（CJK=2）。 */
const TITLE_UNITS = 18;
const SUB_UNITS = 16;
const ACTION_UNITS = 12;

function bezier(x1: number, y1: number, x2: number, y2: number): string {
	const midY = (y1 + y2) / 2;
	return `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
}

function stripeClass(layer: string): string {
	const known = (LAYER_ORDER as readonly string[]).includes(layer)
		? layer
		: 'other';
	return `xy-agent-map__stripe xy-agent-map__stripe--${known}`;
}

function bandClass(layer: string): string {
	const known = (LAYER_ORDER as readonly string[]).includes(layer)
		? layer
		: 'other';
	return `xy-agent-map__band xy-agent-map__band--${known}`;
}

function AgentMapCanvasImpl({
	nodes,
	edges,
	lanes,
	width: _width,
	height: _height,
	selectedId,
	followId,
	focusRequestId,
	onSelect,
	hitByNodeId,
	searchHitIds,
	opsTrail,
	trailAnimate = false,
	replayPath,
	replayVerb,
	stepRunningIds,
	stepSeenIds,
	stepVerbs,
}: Props) {
	void _width;
	void _height;
	const wrapRef = useRef<HTMLDivElement | null>(null);
	const worldRef = useRef<SVGGElement | null>(null);
	const camRef = useRef({...CAM_DEFAULT});
	const drag = useRef<{x: number; y: number; cx: number; cy: number} | null>(
		null,
	);
	const dragged = useRef(false);
	const panRaf = useRef(0);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const userPanned = useRef(false);
	const lastFocusReq = useRef<string | null>(null);

	const paintCam = () => {
		const g = worldRef.current;
		if (!g) {
			return;
		}
		const c = camRef.current;
		g.setAttribute(
			'transform',
			`translate(${c.x} ${c.y}) scale(${c.k})`,
		);
	};

	const schedulePaintCam = () => {
		if (panRaf.current) {
			return;
		}
		panRaf.current = requestAnimationFrame(() => {
			panRaf.current = 0;
			paintCam();
		});
	};

	const centerOn = (node: LaidNode) => {
		const wrap = wrapRef.current;
		if (!wrap) {
			return;
		}
		const vw = wrap.clientWidth;
		const vh = wrap.clientHeight;
		const c = camRef.current;
		camRef.current = {
			k: c.k,
			x: vw / 2 - (node.x + node.w / 2) * c.k,
			y: vh / 2 - (node.y + node.h / 2) * c.k,
		};
		paintCam();
	};

	useEffect(() => {
		userPanned.current = false;
		camRef.current = {...CAM_DEFAULT};
		paintCam();
	}, [nodes.length]);

	useEffect(() => {
		return () => {
			if (panRaf.current) {
				cancelAnimationFrame(panRaf.current);
			}
		};
	}, []);

	const followNode = followId ? nodes.find(n => n.id === followId) : null;
	const followX = followNode?.x;
	const followY = followNode?.y;
	useEffect(() => {
		if (!followId || userPanned.current || followX == null || followY == null) {
			return;
		}
		const node = nodes.find(n => n.id === followId);
		if (!node) {
			return;
		}
		centerOn(node);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [followId, followX, followY]);

	useEffect(() => {
		if (!focusRequestId || focusRequestId === lastFocusReq.current) {
			return;
		}
		const focusId = focusRequestId.split('#')[0] ?? '';
		const node = nodes.find(n => n.id === focusId);
		if (!node) {
			return;
		}
		lastFocusReq.current = focusRequestId;
		userPanned.current = false;
		centerOn(node);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [focusRequestId, nodes]);

	/** 仅选中时压暗邻域；hover 走 CSS，避免每移入节点整图 React 重渲。 */
	const linkedIds = useMemo(() => {
		if (!selectedId) {
			return null;
		}
		const set = new Set<string>([selectedId]);
		const capped = edges.length > EDGE_CAP ? edges.slice(0, EDGE_CAP) : edges;
		for (const edge of capped) {
			if (edge.from === selectedId || edge.to === selectedId) {
				set.add(edge.from);
				set.add(edge.to);
			}
		}
		for (const edge of opsTrail ?? []) {
			if (edge.from === selectedId || edge.to === selectedId) {
				set.add(edge.from);
				set.add(edge.to);
			}
		}
		return set;
	}, [selectedId, edges, opsTrail]);

	const onWheel = (e: ReactWheelEvent<SVGSVGElement>) => {
		e.preventDefault();
		userPanned.current = true;
		const wrap = wrapRef.current;
		if (!wrap) {
			return;
		}
		const rect = wrap.getBoundingClientRect();
		const mx = e.clientX - rect.left;
		const my = e.clientY - rect.top;
		const factor = e.deltaY < 0 ? 1.08 : 0.92;
		const c = camRef.current;
		const nextK = Math.min(2.4, Math.max(0.45, c.k * factor));
		const wx = (mx - c.x) / c.k;
		const wy = (my - c.y) / c.k;
		camRef.current = {
			k: nextK,
			x: mx - wx * nextK,
			y: my - wy * nextK,
		};
		schedulePaintCam();
	};

	const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
		if (e.button !== 0) {
			return;
		}
		dragged.current = false;
		const c = camRef.current;
		drag.current = {x: e.clientX, y: e.clientY, cx: c.x, cy: c.y};
		e.currentTarget.setPointerCapture(e.pointerId);
	};

	const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
		const d = drag.current;
		if (!d) {
			return;
		}
		if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 3) {
			userPanned.current = true;
			dragged.current = true;
		}
		camRef.current = {
			k: camRef.current.k,
			x: d.cx + (e.clientX - d.x),
			y: d.cy + (e.clientY - d.y),
		};
		schedulePaintCam();
	};

	const endDrag = () => {
		drag.current = null;
	};

	const onDoubleClick = (e: ReactPointerEvent<SVGSVGElement>) => {
		e.preventDefault();
		userPanned.current = false;
		camRef.current = {...CAM_DEFAULT};
		paintCam();
		if (followId) {
			const node = nodes.find(n => n.id === followId);
			if (node) {
				requestAnimationFrame(() => centerOn(node));
			}
		}
	};

	const laneBands = lanes ?? [];
	const worldW = Math.max(_width || 0, 480);
	const worldH = Math.max(_height || 0, 320);
	const dimming = Boolean(linkedIds);

	const edgePaths = useMemo(() => {
		const capped = edges.length > EDGE_CAP ? edges.slice(0, EDGE_CAP) : edges;
		return capped.map(edge => ({
			key: `${edge.from}->${edge.to}`,
			from: edge.from,
			to: edge.to,
			d: bezier(edge.x1, edge.y1, edge.x2, edge.y2),
		}));
	}, [edges]);

	const nodeByPath = useMemo(() => {
		const m = new Map<string, LaidNode>();
		for (const node of nodes) {
			m.set(node.id, node);
		}
		return m;
	}, [nodes]);

	const trailGeom = useMemo(() => {
		if (!opsTrail?.length) {
			return [] as Array<{key: string; d: string; from: string; to: string}>;
		}
		const find = (path: string) => {
			const exact = nodeByPath.get(path);
			if (exact) {
				return exact;
			}
			for (const n of nodes) {
				if (pathsLooselyEqual(n.id, path)) {
					return n;
				}
			}
			return null;
		};
		const out: Array<{key: string; d: string; from: string; to: string}> = [];
		for (const edge of opsTrail) {
			const a = find(edge.from);
			const b = find(edge.to);
			if (!a || !b) {
				continue;
			}
			out.push({
				key: `trail:${edge.from}->${edge.to}`,
				from: edge.from,
				to: edge.to,
				d: bezier(
					a.x + a.w / 2,
					a.y + a.h / 2,
					b.x + b.w / 2,
					b.y + b.h / 2,
				),
			});
		}
		return out;
	}, [opsTrail, nodeByPath, nodes]);

	const cam0 = camRef.current;

	return (
		<div
			ref={wrapRef}
			className="xy-agent-map relative h-full min-h-0 w-full overflow-hidden"
		>
			<svg
				className="xy-agent-map__svg h-full w-full cursor-grab touch-none active:cursor-grabbing"
				role="img"
				aria-label="工作区地图"
				onWheel={onWheel}
				onPointerDown={onPointerDown}
				onPointerMove={onPointerMove}
				onPointerUp={endDrag}
				onPointerCancel={endDrag}
				onDoubleClick={onDoubleClick}
			>
				<defs>
					<pattern
						id="xy-map-dots"
						width="18"
						height="18"
						patternUnits="userSpaceOnUse"
					>
						<circle className="xy-agent-map__grid" cx="1" cy="1" r="0.55" />
					</pattern>
					<clipPath id="xy-map-node-clip">
						<rect x={10} y={2} width={128} height={36} rx={4} />
					</clipPath>
					<marker
						id="xy-map-trail-arrow"
						viewBox="0 0 10 10"
						refX="8"
						refY="5"
						markerWidth="6"
						markerHeight="6"
						orient="auto"
						markerUnits="userSpaceOnUse"
					>
						<path
							d="M 0 1.2 L 9 5 L 0 8.8 z"
							className="xy-agent-map__trail-arrow"
						/>
					</marker>
					<marker
						id="xy-map-trail-arrow-hot"
						viewBox="0 0 10 10"
						refX="8"
						refY="5"
						markerWidth="7"
						markerHeight="7"
						orient="auto"
						markerUnits="userSpaceOnUse"
					>
						<path
							d="M 0 1.2 L 9 5 L 0 8.8 z"
							className="xy-agent-map__trail-arrow--hot"
						/>
					</marker>
				</defs>
				<rect width="100%" height="100%" fill="url(#xy-map-dots)" />
				<g
					ref={worldRef}
					transform={`translate(${cam0.x} ${cam0.y}) scale(${cam0.k})`}
				>
					{laneBands.map(band => (
						<g key={`band-${band.layer}`} pointerEvents="none">
							<rect
								x={band.x}
								y={band.y}
								width={band.w}
								height={band.h}
								rx={14}
								className={bandClass(band.layer)}
							/>
							<text
								x={band.x + 14}
								y={band.y + 18}
								className="xy-agent-map__band-label"
							>
								{LAYER_LABELS[band.layer] ?? band.layer}
							</text>
						</g>
					))}
					{edgePaths.map(edge => {
						const hot =
							Boolean(linkedIds) &&
							(edge.from === selectedId || edge.to === selectedId);
						return (
							<path
								key={edge.key}
								d={edge.d}
								className={cn(
									'xy-agent-map__edge',
									dimming && !hot && 'xy-agent-map__edge--dim',
									hot && 'xy-agent-map__edge--hot',
									hot &&
										smoothness &&
										'xy-agent-map__edge--flow',
								)}
								strokeWidth={hot ? 1.8 : 1}
							/>
						);
					})}
					{/* 轨迹在节点下：中心贝塞尔，穿心段被芯片盖住 */}
					{trailGeom.map(edge => {
						const hot =
							Boolean(selectedId) &&
							(edge.from === selectedId || edge.to === selectedId);
						const flowing =
							smoothness && (trailAnimate || hot);
						return (
							<g key={edge.key} className="xy-agent-map__trail-g">
								<path
									d={edge.d}
									className={cn(
										'xy-agent-map__trail',
										hot && 'xy-agent-map__trail--hot',
										dimming && !hot && 'xy-agent-map__trail--dim',
										flowing && 'xy-agent-map__trail--flow',
									)}
									fill="none"
									markerEnd={
										hot
											? 'url(#xy-map-trail-arrow-hot)'
											: 'url(#xy-map-trail-arrow)'
									}
								/>
								{flowing ? (
									<path
										d={edge.d}
										className={cn(
											'xy-agent-map__trail-head',
											hot && 'xy-agent-map__trail-head--hot',
										)}
										fill="none"
									/>
								) : null}
							</g>
						);
					})}
					{nodes.map(node => {
						const hit =
							node.kind === 'file' || node.kind === 'package'
								? (hitByNodeId?.get(node.id) ?? null)
								: null;
						const replayHit =
							Boolean(replayPath) &&
							(node.kind === 'file' || node.kind === 'package') &&
							pathsLooselyEqual(node.id, replayPath!);
						const running =
							replayHit ||
							(node.kind === 'step'
								? Boolean(stepRunningIds?.has(node.id))
								: Boolean(hit?.running));
						const seen =
							replayHit ||
							(node.kind === 'step'
								? Boolean(stepSeenIds?.has(node.id)) || running
								: Boolean(hit));
						const selected = selectedId === node.id || replayHit;
						const searchHit = Boolean(searchHitIds?.has(node.id));
						const dim =
							dimming && linkedIds != null && !linkedIds.has(node.id);
						const actionVerb = replayHit
							? (replayVerb ?? 'replay')
							: node.kind === 'step'
								? (stepVerbs?.get(node.id) ?? null)
								: (hit?.verb ?? null);
						const sub = actionVerb
							? actionVerb
							: node.files != null
								? `${node.files} files`
								: node.layer;
						const rx = 11;
						const actionW =
							running && actionVerb
								? Math.min(76, Math.max(34, actionVerb.length * 6.4 + 14))
								: 0;
						return (
							<g
								key={node.id}
								transform={`translate(${node.x} ${node.y})`}
								className={cn(
									'cursor-pointer',
									'xy-agent-map__node',
									seen && 'xy-agent-map__node--seen',
									running && 'xy-agent-map__node--live',
									replayHit && 'xy-agent-map__node--replay',
									selected && 'xy-agent-map__node--selected',
									searchHit && 'xy-agent-map__node--search',
									dim && 'xy-agent-map__node--dim',
								)}
								onPointerDown={e => e.stopPropagation()}
								onClick={() => {
									if (dragged.current) {
										return;
									}
									onSelect(node.id, node.kind);
								}}
							>
								<title>{`${node.name}\n${node.id}`}</title>
								{running && actionVerb ? (
									<g
										className="xy-agent-map__action"
										transform={`translate(${node.w / 2} -8)`}
									>
										<rect
											x={-actionW / 2}
											y={-9}
											width={actionW}
											height={16}
											rx={8}
											className={cn(
												'xy-agent-map__action-bg',
												replayHit && 'xy-agent-map__action-bg--replay',
											)}
										/>
										<text
											textAnchor="middle"
											y={2.5}
											className="xy-agent-map__action-text"
										>
											{fitLabel(actionVerb, ACTION_UNITS)}
										</text>
									</g>
								) : null}
								<rect
									width={node.w}
									height={node.h}
									rx={rx}
									className="xy-agent-map__node-body"
									strokeWidth={selected || running || searchHit ? 1.5 : 1}
								/>
								<rect
									x={5}
									y={8}
									width={3}
									height={node.h - 16}
									rx={1.5}
									className={stripeClass(node.layer)}
								/>
								{running ? (
									<rect
										width={node.w}
										height={node.h}
										rx={rx}
										className={cn(
											'xy-agent-map__pulse',
											replayHit && 'xy-agent-map__pulse--replay',
											smoothness && 'xy-agent-map__pulse--anim',
										)}
									/>
								) : null}
								<g clipPath="url(#xy-map-node-clip)">
									<text x={12} y={17} className="xy-agent-map__node-title">
										{fitLabel(node.name, TITLE_UNITS)}
									</text>
									<text x={12} y={30} className="xy-agent-map__node-sub">
										{fitLabel(String(sub ?? ''), SUB_UNITS)}
									</text>
								</g>
							</g>
						);
					})}
					<rect
						x={0}
						y={0}
						width={worldW}
						height={worldH}
						fill="transparent"
						pointerEvents="none"
					/>
				</g>
			</svg>
		</div>
	);
}

export const AgentMapCanvas = memo(AgentMapCanvasImpl);

/** 给面板量宽后做泳道排版。 */
export function useLaneLayout(
	items: Array<{
		id: string;
		name: string;
		layer: string;
		files?: number;
		kind?: LaidNode['kind'];
	}>,
	edges: Array<{from: string; to: string}>,
	kind: LaidNode['kind'],
) {
	const hostRef = useRef<HTMLDivElement | null>(null);
	const [laneWidth, setLaneWidth] = useState(360);

	useEffect(() => {
		const el = hostRef.current;
		if (!el) {
			return;
		}
		const apply = () => {
			const next = Math.max(280, el.clientWidth);
			setLaneWidth(w => (Math.abs(w - next) < 1 ? w : next));
		};
		apply();
		const ro = new ResizeObserver(apply);
		ro.observe(el);
		return () => ro.disconnect();
	}, []);

	const laid = useMemo(
		() => layoutLanes(items, edges, kind, laneWidth),
		[items, edges, kind, laneWidth],
	);
	return {hostRef, laid};
}
