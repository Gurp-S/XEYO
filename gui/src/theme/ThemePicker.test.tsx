/**
 * 主题色卡的绘制来源守卫。复现的缺陷（实测见 _design_drafts/reaudit-20260927/r5）：
 * 预览配色写死在组件里（含一个 '#fff'），且强调短条只占约 1.9% 面积、
 * 两条内容线靠 opacity 0.62 / 0.22 叠加 → 十套浅色主题在卡尺寸上糊成同一片浅灰。
 *
 * 这里锁四件事：
 * 1. 组件源码不出现任何字面色；DOM 里出现的每个 rgb 三色组都必须是该主题
 *    元数据里的实色（paper / ink / accent）之一。
 * 2. 强调色在一张卡里至少占两块独立面积（顶部强调条 + 强调短条）。
 * 3. 内容线是实色：不存在 opacity 稀释，且有一条满值墨色标题行。
 * 4. role="listbox" / role="option" 语义、可见文案与键盘选中不变。
 */
import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {THEME_CATALOG, type ThemeMeta} from '@/theme/catalog';
import {ThemePicker} from '@/theme/ThemePicker';
import pickerSrc from './ThemePicker.tsx?raw';

/** 剥掉注释后的组件源码。 */
const pickerCode = pickerSrc
	.replace(/\/\*[\s\S]*?\*\//g, '')
	.split('\n')
	.filter(l => !/^\s*(\/\/|\*)/.test(l))
	.join('\n');

const rgbOf = (hex: string): string => {
	const h = hex.replace('#', '');
	const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
	const n = [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16));
	return `rgb(${n[0]}, ${n[1]}, ${n[2]})`;
};

/** DOM 内联样式里出现的所有 rgb(...) 三色组（color-mix 内部的也算）。 */
function rgbTokens(styleText: string): string[] {
	return [...styleText.matchAll(/rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)/g)].map(m =>
		m[0].replace(/\s+/g, ' '),
	);
}

function spansOf(card: HTMLElement): HTMLElement[] {
	return Array.from(card.querySelectorAll('span')) as HTMLElement[];
}

function styleOf(el: Element): string {
	return (el.getAttribute('style') ?? '').replace(/\s+/g, ' ');
}

/** 该卡（含所有子元素）的全部内联样式文本。 */
function inlineStyles(card: HTMLElement): string[] {
	return [card, ...spansOf(card), ...Array.from(card.querySelectorAll('*'))].map(styleOf);
}

function cardOf(meta: ThemeMeta): HTMLElement {
	return screen.getByRole('option', {name: meta.label});
}

describe('ThemePicker 预览色卡', () => {
	afterEach(cleanup);

	function renderPicker(onChange = vi.fn(), value = 'paper') {
		render(<ThemePicker value={value as never} onChange={onChange} />);
		return onChange;
	}

	it('二十套主题齐全，语义仍是 listbox/option，文案一字不动', () => {
		renderPicker();
		expect(screen.getByRole('listbox')).toHaveAttribute('aria-label', '主题');
		const options = screen.getAllByRole('option');
		expect(options).toHaveLength(THEME_CATALOG.length);
		expect(options).toHaveLength(20);
		expect(options.map(o => o.getAttribute('aria-label'))).toEqual(
			THEME_CATALOG.map(t => t.label),
		);
	});

	it('组件源码不写字面色，DOM 里的颜色全部来自该主题元数据', () => {
		renderPicker();
		expect(pickerCode).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
		expect(pickerCode).not.toMatch(/\brgba?\(/);
		expect(pickerCode).not.toMatch(/\bhsl\(/);
		for (const meta of THEME_CATALOG) {
			const card = cardOf(meta);
			const allowed = new Set(
				Object.values(meta.swatches).map(s => rgbOf(s).replace(/\s+/g, ' ')),
			);
			const seen = inlineStyles(card)
				.flatMap(rgbTokens)
				.filter(t => !allowed.has(t));
			expect(seen, `${meta.id} 出现了元数据之外的色值`).toEqual([]);
		}
	});

	it('卡底与预览底用该主题纸面，边框用由纸墨派生的发丝色', () => {
		renderPicker();
		for (const meta of THEME_CATALOG) {
			const card = cardOf(meta);
			const paper = rgbOf(meta.swatches.paper);
			const ink = rgbOf(meta.swatches.ink);
			expect(styleOf(card)).toContain(`background: ${paper}`);
			const preview = spansOf(card)[0];
			expect(styleOf(preview)).toContain(`background: ${paper}`);
			// 发丝线：同一配比（24% 墨入纸）作用在各主题自己的纸墨上
			expect(styleOf(preview)).toMatch(
				new RegExp(
					`border-color: color-mix\\(in oklab, ${ink.replace(/[(),]/g, '\\$&')} 24%, ${paper.replace(/[(),]/g, '\\$&')}\\)`,
				),
			);
		}
	});

	it('强调色每卡至少两块独立面积（顶部强调条 + 强调短条）', () => {
		renderPicker();
		for (const meta of THEME_CATALOG) {
			const accent = rgbOf(meta.swatches.accent);
			const rows = spansOf(cardOf(meta)).filter(el =>
				new RegExp(`background: ${accent.replace(/[(),]/g, '\\$&')};`).test(styleOf(el)),
			);
			expect(rows.length, `${meta.id} 的 accent 面积块数`).toBeGreaterThanOrEqual(2);
		}
	});

	it('内容线是实色，不再靠 alpha 把墨差稀释掉', () => {
		renderPicker();
		for (const meta of THEME_CATALOG) {
			const lines = spansOf(cardOf(meta)).filter(el => /background:/.test(styleOf(el)));
			expect(lines.length).toBeGreaterThan(0);
			for (const el of lines) {
				expect(styleOf(el)).not.toMatch(/opacity/i);
				expect(el.style.opacity || '1').toBe('1');
			}
			// 必须有一条满值墨色标题行（原来只有 0.62 alpha 的墨）
			const ink = rgbOf(meta.swatches.ink).replace(/[(),]/g, '\\$&');
			expect(
				lines.some(el => new RegExp(`background: ${ink};`).test(styleOf(el))),
				`${meta.id} 应有满值墨色内容线`,
			).toBe(true);
		}
	});

	it('键盘：Tab 聚焦到卡片，Enter / Space 选中该主题', async () => {
		const onChange = renderPicker(vi.fn(), 'mist');
		await userEvent.tab();
		expect(screen.getAllByRole('option')[0]).toHaveFocus();
		await userEvent.keyboard('{Enter}');
		expect(onChange).toHaveBeenCalledWith('paper');
		await userEvent.tab();
		await userEvent.keyboard(' ');
		expect(onChange).toHaveBeenLastCalledWith('pure');
	});

	it('只有当前主题被标为选中', () => {
		renderPicker(vi.fn(), 'steel');
		const selected = screen
			.getAllByRole('option')
			.filter(o => o.getAttribute('aria-selected') === 'true');
		expect(selected).toHaveLength(1);
		expect(selected[0]).toHaveAccessibleName('青钢');
	});
});
