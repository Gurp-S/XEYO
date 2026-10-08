export const FOLLOW_TAIL_PX = 80;
/**
 * 重新贴底：必须真正滚到「底」才重新钉住。
 * 曾经是 32px —— 用户往回翻看时一不留神滚进 32px 内，下一次内容
 * resize 就被 snap 硬拽到底（肉眼可见的跳动）。收到 4px 内才重挂，
 * 重挂瞬间的位移≤4px，无感。
 */
export const FOLLOW_TAIL_ENTER_PX = 4;

/** 用户滚动手势被视为「正在进行」的窗口（期间禁止程序化贴底争抢）。 */
export const USER_GESTURE_FRESH_MS = 350;

let lastUserGestureAt = 0;

/** wheel / 触摸 / 拖动滚动条时调用：记录最后一次用户手势时间。 */
export function noteUserScrollGesture(at: number = Date.now()): void {
	lastUserGestureAt = at;
}

/** 手势窗口内（用户正在主动滚动）→ 程序化跟尾必须让路。 */
export function isUserScrollingFresh(now: number = Date.now()): boolean {
	return now - lastUserGestureAt < USER_GESTURE_FRESH_MS;
}

export function gapFromBottom(
	scrollHeight: number,
	scrollTop: number,
	clientHeight: number,
): number {
	return scrollHeight - scrollTop - clientHeight;
}

export function shouldFollowTail(
	gap: number,
	threshold: number = FOLLOW_TAIL_PX,
): boolean {
	return gap < threshold;
}

/**
 * 更新跟尾钉住状态。
 * - 用户上滚（scrollTop 减小）→ 立刻取消钉住，避免 sticky 改高后被 snap 拉回
 * - 已钉住：gap ≥ FOLLOW_TAIL_PX 才松手
 * - 未钉住：须 gap < FOLLOW_TAIL_ENTER_PX 才重新钉住
 *
 * `contentShrank`：本帧内容高度是否比上次采样矮了。内容变矮（折叠卡收拢、
 * 流式正文替换 settled 正文、视口变宽导致行变短）时，浏览器会把 scrollTop
 * 夹到新的最大可滚值 —— 位移方向与「上滚」一致，视口却仍在底部。这种几何
 * 夹持不是用户意图：把它当成上滚，会让钉住状态在一次折叠后被永久打掉，
 * 此后整段流式都不再跟随（视口往上跳一截后卡住，新输出堆在视野下方）。
 * 只在「原本已钉住 + 收缩 + 仍在底部」时按夹持处理（保持钉住）。
 */
export function nextFollowTailPinned(
	wasPinned: boolean,
	gap: number,
	scrolledUp: boolean,
	contentShrank: boolean = false,
): boolean {
	if (scrolledUp) {
		// 收缩把 scrollTop 夹到新的最大可滚值：方向像上滚，视口却仍在底部。
		// 已钉住 → 保持钉住（否则一次折叠就永久松手）；未钉住 → 不得借此
		// 重钉（用户本来在回看历史，收缩不该把视口拽回底部）。
		const geometricClamp =
			wasPinned && contentShrank && gap <= FOLLOW_TAIL_ENTER_PX;
		return geometricClamp;
	}
	if (wasPinned) {
		return gap < FOLLOW_TAIL_PX;
	}
	return gap < FOLLOW_TAIL_ENTER_PX;
}

/** 仅在仍钉住底部时写 scrollTop；用户上滚时不跟尾。 */
export function writeFollowTail(
	el: {scrollTop: number; scrollHeight: number},
	pinned: boolean,
): boolean {
	if (!pinned) {
		return false;
	}
	el.scrollTop = el.scrollHeight;
	return true;
}
