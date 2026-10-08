import {describe, expect, it} from 'vitest';
import {
	FOLLOW_TAIL_ENTER_PX,
	FOLLOW_TAIL_PX,
	gapFromBottom,
	isUserScrollingFresh,
	nextFollowTailPinned,
	noteUserScrollGesture,
	shouldFollowTail,
	writeFollowTail,
} from './chatScroll';

describe('follow-tail scroll', () => {
	it('pins when the gap is under the threshold', () => {
		expect(gapFromBottom(1000, 920, 80)).toBe(0);
		expect(shouldFollowTail(0, FOLLOW_TAIL_PX)).toBe(true);
		expect(shouldFollowTail(79)).toBe(true);
		expect(shouldFollowTail(80)).toBe(false);
	});

	it('does not write scrollTop when the user has scrolled up', () => {
		const el = {scrollHeight: 1000, scrollTop: 100};
		expect(writeFollowTail(el, false)).toBe(false);
		expect(el.scrollTop).toBe(100);
	});

	it('writes scrollTop only while pinned', () => {
		const el = {scrollHeight: 1000, scrollTop: 100};
		expect(writeFollowTail(el, true)).toBe(true);
		expect(el.scrollTop).toBe(1000);
	});

	it('unpins immediately on upward scroll', () => {
		expect(nextFollowTailPinned(true, 10, true)).toBe(false);
		expect(nextFollowTailPinned(false, 10, true)).toBe(false);
	});

	it('keeps pinning when shrinking content clamps scrollTop', () => {
		// 流式正文替换 settled 正文 / 折叠卡收拢：scrollTop 被浏览器夹下来
		// （方向像上滚），但视口仍在底部 —— 不是用户上滚，不得松手。
		expect(nextFollowTailPinned(true, 0, true, true)).toBe(true);
	});

	it('never re-pins a user who is reading history when content shrinks', () => {
		// 未钉住时收缩不得借机重钉：用户在上方回看历史，收缩把视口夹到
		// 新的底部（gap=0），这同样不是「用户滚回底部」。
		expect(nextFollowTailPinned(false, 0, true, true)).toBe(false);
	});

	it('still unpins when the user scrolled away during a shrink', () => {
		// 收缩同时用户确实滚开了（gap 超出重新钉住阈值）→ 尊重用户上滚。
		expect(nextFollowTailPinned(true, 600, true, true)).toBe(false);
		expect(nextFollowTailPinned(false, 600, true, true)).toBe(false);
	});

	it('uses enter/exit hysteresis when not scrolling up', () => {
		expect(nextFollowTailPinned(true, FOLLOW_TAIL_PX - 1, false)).toBe(true);
		expect(nextFollowTailPinned(true, FOLLOW_TAIL_PX, false)).toBe(false);
		expect(nextFollowTailPinned(false, FOLLOW_TAIL_ENTER_PX, false)).toBe(false);
		expect(nextFollowTailPinned(false, FOLLOW_TAIL_ENTER_PX - 1, false)).toBe(
			true,
		);
	});

	it('re-pin hysteresis stays imperceptibly small', () => {
		// 重新钉住的瞬间 snap 位移 ≤ 4px，否则表现为滚动条乱跳。
		expect(FOLLOW_TAIL_ENTER_PX).toBeLessThanOrEqual(4);
	});

	it('tracks user gesture freshness for snap yielding', () => {
		expect(isUserScrollingFresh(10_000)).toBe(false);
		noteUserScrollGesture(10_000);
		expect(isUserScrollingFresh(10_000 + 100)).toBe(true);
		expect(isUserScrollingFresh(10_000 + 349)).toBe(true);
		expect(isUserScrollingFresh(10_000 + 351)).toBe(false);
	});
});
