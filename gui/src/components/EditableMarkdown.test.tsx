/**
 * EditableMarkdown.test.tsx — 组词中的 Tab 不许被缩进处理器截走。
 *
 * contentEditable 走 execCommand 插入（jsdom 无此 API），插入本身不在
 * 本档可测面；这里钉的是闸：组词中不 preventDefault（按键交还输入法），
 * 真实 Tab 照旧 preventDefault。行为等价性由既有 e2e（源码编辑轮）兜。
 */
import {cleanup, fireEvent, render} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {EditableMarkdown} from '@/components/EditableMarkdown';

afterEach(() => {
	cleanup();
});

function mount() {
	const onChange = vi.fn();
	const {container} = render(
		<EditableMarkdown content={'hello'} onChange={onChange} />,
	);
	const root = container.querySelector('.xy-md-editable') as HTMLElement;
	return {root};
}

describe('EditableMarkdown 的 Tab', () => {
	it('组词中的 Tab 不被截走（交还输入法）', () => {
		const {root} = mount();
		const prevented = !fireEvent.keyDown(root, {key: 'Tab', isComposing: true});
		expect(prevented).toBe(false);
	});

	it('真实 Tab 照旧 preventDefault（回归护栏）', () => {
		const {root} = mount();
		const prevented = !fireEvent.keyDown(root, {key: 'Tab'});
		expect(prevented).toBe(true);
	});
});
