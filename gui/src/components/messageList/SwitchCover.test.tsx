/**
 * 切换覆盖层的壁纸守卫（SwitchCover 与 switchLag 此前零测试，缺陷才能静默上线）。
 *
 * 复现的缺陷：覆盖层盖的是不透明 bg-paper，而开壁纸时聊天区是半透的（评审表面 78% 纸
 * 压在 L0 壁纸上）——纸面一盖，实测聊天区 84% 面积的像素平均 L1 色差 53，两帧 = 肉眼可见的一闪。
 * 改成复刻 L0（与吸顶 pin 同一套 --xy-bg-* 层源）后同一掩码上 p50 色差 = 2。
 *
 * 钉两条判据：
 * ① 有壁纸时才写背景位置，且必须写成三值列表 —— 单个位置会被三层共用，把两张压色
 *    渐变一起推走，覆盖层会露出没压色的原图（我自己第一版就是这么错的）；
 * ② 没开壁纸时一律不写内联背景（覆盖层保持原样，别把无壁纸用户拖进新路径）。
 */
import {cleanup, render} from '@testing-library/react';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {afterEach, describe, expect, it, vi} from 'vitest';

vi.mock('@/stores/chat/switchLag', () => ({
	useSwitchLag: () => ({displayed: 'a', lagging: true}),
}));

const {SwitchCover} = await import('./SwitchCover');

function coverIn(wallpaper: boolean): HTMLElement | null {
	const {container} = render(
		<div data-review-wallpaper={wallpaper ? '1' : undefined}>
			<SwitchCover />
		</div>,
	);
	return container.querySelector('.xy-switch-cover');
}

describe('SwitchCover 壁纸复刻', () => {
	afterEach(cleanup);

	it('开壁纸：背景位置是三值列表，只平移壁纸层', () => {
		const el = coverIn(true);
		expect(el).not.toBeNull();
		const parts = (el as HTMLElement).style.backgroundPosition
			.split(',')
			.map((s) => s.trim());
		expect(parts).toHaveLength(3);
		expect(parts[0]).toBe('0px 0px');
		expect(parts[1]).toBe('0px 0px');
		expect(parts[2]).toMatch(/^-?\d+px -?\d+px$/);
	});

	it('没开壁纸：不写内联背景位置', () => {
		const el = coverIn(false);
		expect(el).not.toBeNull();
		expect((el as HTMLElement).style.backgroundPosition).toBe('');
	});

	/* jsdom 不加载样式表，上面两条量不到 chat.css 那三层 —— 删掉规则只有像素能发现，
	   所以在这里按源码扫一遍：复刻层必须在，且必须被壁纸门圈住。 */
	it('chat.css 里覆盖层的壁纸复刻还在，且只在开壁纸时命中', () => {
		const css = readFileSync(
			resolve(process.cwd(), 'src/styles/chat.css'),
			'utf8',
		).replace(/\/\*[\s\S]*?\*\//g, '');
		const blocks = css
			.split('}')
			.map((b) => b.replace(/\s+/g, ' ').trim())
			.filter((b) => b.includes('.xy-switch-cover'));
		expect(blocks.length).toBeGreaterThanOrEqual(2);
		const main = blocks.find((b) => b.includes('background-image'));
		expect(main).toBeDefined();
		expect(main as string).toMatch(
			/^\.xy-app-surface\[data-review-wallpaper="1"\] \.xy-switch-cover \{/,
		);
		expect(main as string).toContain(
			'linear-gradient(var(--xy-cover-tint), var(--xy-cover-tint))',
		);
		expect(main as string).toContain(
			'linear-gradient(var(--xy-bg-veil-composited), var(--xy-bg-veil-composited))',
		);
		expect(main as string).toContain('var(--xy-bg-image)');
		expect(main as string).toContain('var(--xy-bg-draw-size)');
		const tint = blocks.find((b) =>
			/^\.xy-review-layout\[data-review-wallpaper="1"\] \.xy-switch-cover \{/.test(
				b,
			),
		);
		expect(tint).toBeDefined();
		expect(tint as string).toContain('--xy-cover-tint: var(--xy-review-surface)');
	});
});
