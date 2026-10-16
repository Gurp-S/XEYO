import {describe, expect, it} from 'vitest';
import {renderDeferred} from '@/test/renderDeferred';
import {StreamingMarkdown} from '../components/StreamingMarkdown';

describe('rehypeSafeHtml via StreamingMarkdown', () => {
	it('renders whitelisted html with style on div/span', async () => {
		const {container} = await renderDeferred(
			<StreamingMarkdown
				final
				text={'<div style="color: red;">红字内容</div>'}
			/>,
		);
		const div = container.querySelector('div[style]');
		expect(div?.textContent).toContain('红字内容');
	});

	it('renders details/summary and drops script subtree entirely', async () => {
		const {container} = await renderDeferred(
			<StreamingMarkdown
				final
				text={
					'<details><summary>点击展开</summary>内容区</details>\n\n<script>alert(1)</script>'
				}
			/>,
		);
		expect(container.querySelector('details')).toBeTruthy();
		expect(container.querySelector('summary')?.textContent).toBe('点击展开');
		expect(container.textContent).toContain('内容区');
		expect(container.textContent).not.toContain('alert');
		expect(container.querySelector('script')).toBeNull();
	});

	it('unwraps unknown tags keeping children', async () => {
		const {container} = await renderDeferred(
			<StreamingMarkdown final text={'<custom-tag>保留我</custom-tag>'} />,
		);
		expect(container.querySelector('custom-tag')).toBeNull();
		expect(container.textContent).toContain('保留我');
	});

	it('strips style on non-whitelisted tags and event handlers', async () => {
		const {container} = await renderDeferred(
			<StreamingMarkdown
				final
				text={'<p style="color: red;" onclick="x()">段落内容</p>'}
			/>,
		);
		const p = container.querySelector('p');
		expect(p?.getAttribute('style')).toBeNull();
		expect(p?.getAttribute('onclick')).toBeNull();
		expect(p?.textContent).toBe('段落内容');
	});
});
