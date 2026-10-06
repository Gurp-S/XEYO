/**
 * TextFileEditor.test.tsx — 组词中的 Tab 属于输入法：不许被缩进插入器截走。
 *
 * 同族已有闸：Composer（onKeyDown 首行）、useModalA11y（Tab 陷阱）、
 * promptDialog（Enter）。本编辑器此前漏网：任何 Tab 都 preventDefault +
 * 插 \t，组词候选选择/上屏被扯断。真实 Tab 的行为必须原样保留。
 */
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {TextFileEditor} from '@/components/TextFileEditor';

afterEach(() => {
	cleanup();
});

function mount() {
	const onChange = vi.fn();
	render(<TextFileEditor value="ab" onChange={onChange} aria-label="源码" />);
	return {onChange, ta: screen.getByRole('textbox', {name: '源码'})};
}

describe('TextFileEditor 的 Tab', () => {
	it('组词中的 Tab 不插缩进（交还输入法）', () => {
		const {onChange, ta} = mount();
		const prevented = !fireEvent.keyDown(ta, {key: 'Tab', isComposing: true});
		expect(prevented).toBe(false);
		expect(onChange).not.toHaveBeenCalled();
	});

	it('真实 Tab 照旧插入 \\t（回归护栏）', () => {
		const {onChange, ta} = mount();
		const prevented = !fireEvent.keyDown(ta, {key: 'Tab'});
		expect(prevented).toBe(true);
		expect(onChange).toHaveBeenCalledWith('\tab');
	});
});
