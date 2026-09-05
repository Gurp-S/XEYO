import {describe, expect, it} from 'vitest';
import {
	acquireSelfWallpaper,
	releaseSelfWallpaper,
	syncPromptClampOverflow,
} from './stickyGeometry';
import {STICKY_SELF_WALLPAPER} from './stickyTypes';

function chipFixture(overflow: boolean): {
	chip: HTMLElement;
	clamp: HTMLElement;
} {
	const chip = document.createElement('div');
	chip.className = 'xy-user-prompt';
	chip.style.maxHeight = '96px';
	chip.style.overflow = 'hidden';
	const clamp = document.createElement('div');
	clamp.className = 'xy-prompt-clamp';
	const text = document.createElement('div');
	text.className = 'xy-chat-text';
	text.textContent = 'x'.repeat(overflow ? 4000 : 4);
	clamp.appendChild(text);
	chip.appendChild(clamp);
	document.body.appendChild(chip);
	return {chip, clamp};
}

describe('stickyGeometry wallpaper refcount', () => {
	it('keeps the html attr alive until the last holder releases', () => {
		const doc = document.documentElement;
		if (!STICKY_SELF_WALLPAPER) {
			// 灰度关闭时 acquire/release 为 no-op，契约随之失效——跳过。
			expect(STICKY_SELF_WALLPAPER).toBe(false);
			return;
		}
		doc.removeAttribute('data-xy-selfwallpaper');

		acquireSelfWallpaper();
		acquireSelfWallpaper();
		expect(doc.getAttribute('data-xy-selfwallpaper')).toBe('1');

		// 第一实例卸载不得删除——另一实例仍依赖（主聊天 + 沉浸层并存场景）。
		releaseSelfWallpaper();
		expect(doc.getAttribute('data-xy-selfwallpaper')).toBe('1');

		// 最后一个释放才删除。
		releaseSelfWallpaper();
		expect(doc.hasAttribute('data-xy-selfwallpaper')).toBe(false);
	});
});

describe('stickyGeometry syncPromptClampOverflow', () => {
	it('marks the host chip data-xy-overflow=1 when content overflows', () => {
		const {chip} = chipFixture(true);
		const clamp = chip.querySelector<HTMLElement>('.xy-prompt-clamp')!;
		// jsdom 无真实排版：直接喂可观测几何。clamp 全高 >> chip 可见高。
		Object.defineProperty(chip, 'scrollHeight', {configurable: true, value: 500});
		Object.defineProperty(chip, 'clientHeight', {configurable: true, value: 96});
		syncPromptClampOverflow(clamp);
		expect(chip.dataset.xyOverflow).toBe('1');
		chip.remove();
	});

	it('clears data-xy-overflow when content fits', () => {
		const {chip} = chipFixture(false);
		const clamp = chip.querySelector<HTMLElement>('.xy-prompt-clamp')!;
		chip.dataset.xyOverflow = '1'; // 残留旧标（如退出编辑/吸顶后）
		Object.defineProperty(chip, 'scrollHeight', {configurable: true, value: 40});
		Object.defineProperty(chip, 'clientHeight', {configurable: true, value: 96});
		syncPromptClampOverflow(clamp);
		expect(chip.dataset.xyOverflow).toBe('0');
		chip.remove();
	});

	it('no-ops when clamp has no host chip', () => {
		const orphan = document.createElement('div');
		orphan.className = 'xy-prompt-clamp';
		document.body.appendChild(orphan);
		expect(() => syncPromptClampOverflow(orphan)).not.toThrow();
		orphan.remove();
	});
});
