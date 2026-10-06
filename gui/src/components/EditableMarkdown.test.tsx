/**
 * EditableMarkdown.test.tsx — 组词 Tab 闸 + 粘贴图片链（#13）。
 *
 * contentEditable 走 execCommand 插入（jsdom 无此 API，自动降级到 Selection
 * 插入——测试需先把选区放进编辑根）；行为等价性由既有 e2e（源码编辑轮）兜。
 */
import {cleanup, fireEvent, render, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';

const uploadMedia = vi.fn();
vi.mock('@/lib/api', async importOriginal => {
	const mod = await importOriginal<typeof import('@/lib/api')>();
	return {...mod, uploadMedia: (...args: unknown[]) => uploadMedia(...args)};
});

const toast = {error: vi.fn(), info: vi.fn(), success: vi.fn(), warn: vi.fn(), dismiss: vi.fn()};
vi.mock('@/lib/toast', () => ({toast}));

const {EditableMarkdown} = await import('@/components/EditableMarkdown');

afterEach(() => {
	cleanup();
	uploadMedia.mockReset();
	toast.error.mockReset();
});

function mount() {
	const onChange = vi.fn();
	const {container} = render(
		<EditableMarkdown content={'hello'} onChange={onChange} />,
	);
	const root = container.querySelector('.xy-md-editable') as HTMLElement;
	return {container, root};
}

/** jsdom 无 execCommand：insertPlain 走 Selection 回退，先把光标放进编辑根。 */
function putCaretIn(root: HTMLElement) {
	const sel = window.getSelection();
	const range = document.createRange();
	range.selectNodeContents(root);
	range.collapse(false);
	sel?.removeAllRanges();
	sel?.addRange(range);
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

describe('EditableMarkdown 粘贴图片（#13）', () => {
	it('图片文件 → 上传后插入 xeyo-media 引用', async () => {
		uploadMedia.mockResolvedValue({media_ref: 'xeyo-media://' + 'a'.repeat(64)});
		const {container, root} = mount();
		putCaretIn(root);
		const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', {
			type: 'image/png',
		});
		fireEvent.paste(root, {
			clipboardData: {files: [file], getData: () => ''},
		});
		await waitFor(() => {
			expect(uploadMedia).toHaveBeenCalledTimes(1);
			expect(container.textContent).toContain('xeyo-media://');
		});
	});

	it('上传失败必须出声，不静默吞', async () => {
		uploadMedia.mockRejectedValue(new Error('图片上传接口 500'));
		const {root} = mount();
		putCaretIn(root);
		const file = new File([new Uint8Array([1])], 'shot.png', {
			type: 'image/png',
		});
		fireEvent.paste(root, {
			clipboardData: {files: [file], getData: () => ''},
		});
		await waitFor(() => {
			expect(toast.error).toHaveBeenCalledWith(
				expect.stringContaining('500'),
			);
		});
	});

	it('混合「文本+图片」：文本照常插入，图片走上传链', async () => {
		uploadMedia.mockResolvedValue({media_ref: 'xeyo-media://' + 'b'.repeat(64)});
		const {container, root} = mount();
		putCaretIn(root);
		const file = new File([new Uint8Array([1])], 'shot.png', {
			type: 'image/png',
		});
		fireEvent.paste(root, {
			clipboardData: {files: [file], getData: () => 'MIXED-TEXT'},
		});
		await waitFor(() => {
			expect(container.textContent).toContain('MIXED-TEXT');
			expect(container.textContent).toContain('xeyo-media://');
		});
	});
});

describe('xeyo-media 图片引用渲染（#13 的另一半）', () => {
	it('插入的引用渲染为后端只读地址', () => {
		const ref = 'xeyo-media://' + 'c'.repeat(64);
		const {container} = render(
			<EditableMarkdown content={`![s](${ref})`} onChange={() => {}} />,
		);
		const img = container.querySelector('img');
		expect(img?.getAttribute('src')).toContain('/v1/media/');
	});
});
