/**
 * FilesChanged 的可见文案契约。
 *
 * 背景：退回 09-17 视觉层时 FilesChanged.tsx 一起回到 HEAD 的英文态
 * （时间线那一轮的中文化当时没提交）。业主常设裁定是「界面文案一律中文」，
 * 这里把三条串钉住，避免下一次回退再把英文带回来。
 *
 * 折叠阈值 PREVIEW = 6，所以必须给 7 个以上文件才会出现「显示其余 N 个文件」——
 * 浏览器里用 3 文件的夹具量不到这一条，故由本测试覆盖。
 */
import {cleanup, render} from '@testing-library/react';
import {afterEach, describe, expect, it} from 'vitest';
import type {ChangedFile} from '@/lib/toolActivity';
import {FilesChanged} from './FilesChanged';

afterEach(cleanup);

const mk = (n: number): ChangedFile[] =>
	Array.from({length: n}, (_, i) => ({
		path: `src/mod${i}.ts`,
		name: `mod${i}.ts`,
		add: i + 1,
		del: i,
	}));

describe('FilesChanged 界面文案', () => {
	it('标题与计数走中文，不带英文单复数变形', () => {
		const {container} = render(<FilesChanged files={mk(3)} />);
		expect(container.querySelector('.xy-panel-ask-title')?.textContent).toBe('文件变更');
		expect(container.querySelector('.xy-panel-ask-count')?.textContent).toContain('3 个文件');
	});

	it('超过折叠阈值时给出中文的「显示其余 N 个文件」', () => {
		const {container} = render(<FilesChanged files={mk(8)} />);
		const btn = [...container.querySelectorAll('button')].find(b =>
			/显示其余/.test(b.textContent || ''),
		);
		expect(btn, '8 个文件应触发 6 条折叠').toBeDefined();
		expect(btn!.textContent).toContain('2');
		// 反向钉住：英文态不得回来
		expect(container.textContent).not.toMatch(/\bShow \d+ more\b/);
		expect(container.textContent).not.toMatch(/\bChanges\b/);
		expect(container.textContent).not.toMatch(/\d files\b/);
	});
});
