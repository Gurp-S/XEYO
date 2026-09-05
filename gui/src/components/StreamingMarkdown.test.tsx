import {describe, expect, it} from 'vitest';
import {render} from '@testing-library/react';
import {StreamingMarkdown} from './StreamingMarkdown';

describe('StreamingMarkdown heavy paths', () => {
	it('renders an established table without pipe source', () => {
		const {container} = render(
			<StreamingMarkdown text={'| A | B |\n| --- | --- |\n| 1 | hello'} />,
		);
		expect(container.querySelector('table')).toBeTruthy();
		expect(container.textContent).toContain('hello');
		expect(container.textContent).not.toContain('|');
		expect(container.textContent).not.toContain('---');
	});

	it('pending delimiter never shows raw dashes or pipes', () => {
		const {container} = render(
			<StreamingMarkdown text={'| Name | Age |\n| ---'} />,
		);
		expect(container.textContent).toContain('Name');
		expect(container.textContent).toContain('Age');
		expect(container.textContent).not.toMatch(/\|/);
		expect(container.textContent).not.toContain('---');
	});

	it('renders an open fence via CodeBlock without backticks', () => {
		const {container} = render(
			<StreamingMarkdown text={'```ts\nconst x = 1'} />,
		);
		expect(container.querySelector('.xy-stream-code')).toBeTruthy();
		expect(container.textContent).toContain('const x = 1');
		expect(container.textContent).not.toContain('```');
	});

	it('holds growing fence closers out of the code body', () => {
		const {container} = render(
			<StreamingMarkdown text={'```ts\nconst x = 1\n``'} />,
		);
		expect(container.textContent).toContain('const x = 1');
		expect(container.textContent).not.toContain('``');
	});

	it('renders plain streaming prose with tail fade chars', () => {
		const {container} = render(<StreamingMarkdown text={'Hello'} />);
		expect(container.textContent).toContain('Hello');
		expect(container.querySelector('.xy-streamdown-live')).toBeTruthy();
		expect(container.querySelectorAll('.xy-char').length).toBeGreaterThan(0);
	});
});
