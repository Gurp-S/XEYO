/**
 * 遗留多 Agent 锚点（旧管线：分配说明 | 卡片 | 汇总）。
 * Agent 已改为普通工具；主 UI 走正常 turn 流，仅用 stripAgentAnchor 清掉残片。
 */
export const XEYO_AGENTS_ANCHOR = '<!--xeyo:agents-->';

const ANCHOR_RE = /\n*<!--\s*xeyo:agents\s*-->\n*/i;
/** 兼容旧落盘：分配说明与汇总之间的 --- */
const FALLBACK_RE = /\n\n---\n\n/;

export type AgentAnchorSplit = {
	before: string;
	after: string;
	anchored: boolean;
};

/** 去掉分配段末尾误漏的 `[`（JSON 数组起点曾被流进主气泡）。 */
function scrubAllocationTail(text: string): string {
	return text.replace(/\n\[\s*$/u, '\n').replace(/\[\s*$/u, '').trimEnd();
}

export function splitAtAgentAnchor(text: string): AgentAnchorSplit {
	const raw = text || '';
	if (!raw) {
		return {before: '', after: '', anchored: false};
	}
	let m = raw.match(ANCHOR_RE);
	let viaFallback = false;
	if (!m) {
		m = raw.match(FALLBACK_RE);
		viaFallback = Boolean(m);
	}
	if (!m || m.index == null) {
		return {before: scrubAllocationTail(raw), after: '', anchored: false};
	}
	const before = scrubAllocationTail(raw.slice(0, m.index));
	const after = raw.slice(m.index + m[0].length).replace(/^\n+/, '');
	return {before, after, anchored: true || viaFallback};
}

/** 从展示用 Markdown 中移除锚点注释（未拆开时的兜底）。 */
export function stripAgentAnchor(text: string): string {
	return (text || '').replace(ANCHOR_RE, '\n\n').replace(/\n{3,}/g, '\n\n');
}
