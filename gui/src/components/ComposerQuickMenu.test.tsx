import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {ComposerQuickMenu} from './ComposerQuickMenu';

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

function renderQuick(opts: {
	open?: boolean;
	agentMode?: 'agent' | 'plan' | 'ask';
	multiAgent?: boolean;
	uploading?: boolean;
	onSelectMode?: (m: 'agent' | 'plan' | 'ask') => void;
	onToggleMultiAgent?: () => void;
	onAddFile?: () => void;
	onRunMcp?: () => void;
} = {}) {
	const props = {
		open: opts.open ?? true,
		agentMode: opts.agentMode ?? 'agent',
		multiAgent: opts.multiAgent ?? false,
		uploading: opts.uploading ?? false,
		onSelectMode: opts.onSelectMode ?? vi.fn(),
		onToggleMultiAgent: opts.onToggleMultiAgent ?? vi.fn(),
		onAddFile: opts.onAddFile ?? vi.fn(),
		onRunMcp: opts.onRunMcp ?? vi.fn(),
	};
	const utils = render(<ComposerQuickMenu {...props} />);
	return {...utils, props};
}

describe('ComposerQuickMenu', () => {
	it('renders plain-text search, modes, Files and MCP rows', () => {
		renderQuick();
		expect(screen.getByPlaceholderText('Search modes, actions…')).toBeTruthy();
		expect(screen.getByText('Plan')).toBeTruthy();
		expect(screen.getByText('Ask')).toBeTruthy();
		expect(screen.getByText('Multi-Agent')).toBeTruthy();
		expect(screen.getByText('Files')).toBeTruthy();
		expect(screen.getByText('MCP')).toBeTruthy();
	});

	it('marks active mode with a check and selects on click', async () => {
		const onSelectMode = vi.fn();
		renderQuick({agentMode: 'plan', onSelectMode});
		const planRow = screen.getByRole('menuitemradio', {name: /Plan/});
		expect(planRow.getAttribute('aria-checked')).toBe('true');
		await userEvent.click(screen.getByRole('menuitemradio', {name: /Ask/}));
		expect(onSelectMode).toHaveBeenCalledWith('ask');
	});

	it('marks Multi-Agent as a checkable toggle', async () => {
		const onToggleMultiAgent = vi.fn();
		renderQuick({multiAgent: true, onToggleMultiAgent});
		const row = screen.getByRole('menuitemradio', {name: /Multi-Agent/});
		expect(row.getAttribute('aria-checked')).toBe('true');
		await userEvent.click(row);
		expect(onToggleMultiAgent).toHaveBeenCalled();
	});

	it('filters modes by the search query', async () => {
		renderQuick();
		await userEvent.type(
			screen.getByPlaceholderText('Search modes, actions…'),
			'plan',
		);
		expect(screen.getByText('Plan')).toBeTruthy();
		expect(screen.queryByText('Ask')).toBeNull();
		expect(screen.queryByText('Multi-Agent')).toBeNull();
	});

	it('shows a no-match hint when nothing filters', async () => {
		renderQuick();
		await userEvent.type(
			screen.getByPlaceholderText('Search modes, actions…'),
			'zzzzzz',
		);
		expect(screen.getByText('无匹配项。')).toBeTruthy();
	});

	it('invokes onAddFile and onRunMcp', async () => {
		const onAddFile = vi.fn();
		const onRunMcp = vi.fn();
		renderQuick({onAddFile, onRunMcp});
		await userEvent.click(screen.getByRole('menuitem', {name: 'Files'}));
		expect(onAddFile).toHaveBeenCalled();
		await userEvent.click(screen.getByRole('menuitem', {name: 'MCP'}));
		expect(onRunMcp).toHaveBeenCalled();
	});
});
