/**
 * 排队 dock 的呈现规则（纯函数，便于单测）。
 *
 * 对齐 DSH 的 `QueueDock`（packages/client/ui-conversation/src/client/queue/
 * QueueDock.tsx:104-116）：0 条不渲染；1 条不出计数头、直接一行；
 * 多于 1 条默认折叠成计数头；有行内编辑或动作在飞时**强制展开**；
 * 队列清空后收回折叠态，下次出现队列不沿用旧展开态。
 */

import {MEDIA_REF_RE} from '@/lib/api/core';

export type QueueDockView = {
	/** 是否显示「N 条排队消息」计数头（只有多条时才有）。 */
	readonly showHeader: boolean;
	/** 当前是否处于展开态（含被交互强制展开）。 */
	readonly expanded: boolean;
	/** 列表是否渲染：单条恒可见，多条看展开态。 */
	readonly listVisible: boolean;
};

/** 由折叠偏好 + 交互态算出这一帧的 dock 形态。 */
export function queueDockView(input: {
	count: number;
	collapsed: boolean;
	interactionActive: boolean;
}): QueueDockView {
	const expanded = !input.collapsed || input.interactionActive;
	return {
		showHeader: input.count > 1,
		expanded,
		listVisible: input.count === 1 || expanded,
	};
}

/** 清空后该收回折叠态（已在折叠态则不动，避免无谓重渲染）。 */
export function shouldCollapseQueueDock(count: number, collapsed: boolean): boolean {
	return count === 0 && !collapsed;
}

export function queueCountLabel(count: number): string {
	return `${count} 条排队消息`;
}

/**
 * 排队行里可按图片渲染的媒体引用。非媒体引用（未来的别的形态）留空，
 * 宁可不出缩略图也不拿一个解不开的串去 <img>。
 */
export function queueImageRefs(mediaRefs: readonly string[] | undefined): string[] {
	return (mediaRefs ?? []).filter(ref => MEDIA_REF_RE.test((ref || '').trim()));
}
