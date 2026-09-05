import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {WorkspaceAddButton} from './WorkspaceAddMenu';

vi.mock('@/lib/openFolder', () => ({
	pickFolder: vi.fn(async () => 'D:\\lea\\picked'),
}));

vi.mock('@/lib/workspaceAdd', async () => {
	const actual = await vi.importActual<typeof import('@/lib/workspaceAdd')>(
		'@/lib/workspaceAdd',
	);
	return {
		...actual,
		listGitRepos: vi.fn(async () => ['D:\\lea\\claude']),
		createDirectory: vi.fn(),
		createEmptyProject: vi.fn(),
		gitClone: vi.fn(),
		pickNewFolderPath: vi.fn(),
	};
});

afterEach(() => {
	cleanup();
});

const recents = [
	{path: 'D:\\lea\\XenYon code', name: 'XenYon code'},
	{path: 'D:\\lea\\claude', name: 'claude'},
];

describe('WorkspaceAddButton', () => {
	it('opens an add menu with Recents and Repos actions', async () => {
		const user = userEvent.setup();
		const onOpenPath = vi.fn(async () => undefined);
		render(
			<WorkspaceAddButton recents={recents} onOpenPath={onOpenPath} />,
		);

		await user.click(screen.getByRole('button', {name: '添加工作区'}));
		expect(await screen.findByRole('dialog', {name: '添加工作区'})).toBeTruthy();
		expect(screen.getByPlaceholderText('Search folders, repos...')).toBeTruthy();
		expect(screen.getByText('Recents')).toBeTruthy();
		expect(screen.getByText('D:\\lea\\XenYon code')).toBeTruthy();
		expect(screen.getByText('Repos')).toBeTruthy();
		expect(screen.getByRole('button', {name: 'On This PC'})).toBeTruthy();
		expect(screen.getByRole('button', {name: 'Cloud'})).toBeTruthy();
		expect(screen.getByRole('button', {name: 'Start from scratch'})).toBeTruthy();
		expect(screen.getByRole('button', {name: 'Use Existing...'})).toBeTruthy();
		expect(screen.getByRole('button', {name: 'New Folder'})).toBeTruthy();
	});

	it('filters recents from the search box', async () => {
		const user = userEvent.setup();
		render(
			<WorkspaceAddButton recents={recents} onOpenPath={vi.fn(async () => undefined)} />,
		);
		await user.click(screen.getByRole('button', {name: '添加工作区'}));
		await user.type(
			screen.getByPlaceholderText('Search folders, repos...'),
			'claude',
		);
		expect(screen.getByText('D:\\lea\\claude')).toBeTruthy();
		expect(screen.queryByText('D:\\lea\\XenYon code')).toBeNull();
	});

	it('opens a recent path', async () => {
		const user = userEvent.setup();
		const onOpenPath = vi.fn(async () => undefined);
		render(<WorkspaceAddButton recents={recents} onOpenPath={onOpenPath} />);
		await user.click(screen.getByRole('button', {name: '添加工作区'}));
		await user.click(screen.getByText('D:\\lea\\XenYon code'));
		expect(onOpenPath).toHaveBeenCalledWith('D:\\lea\\XenYon code');
		await waitFor(() => {
			expect(screen.queryByRole('dialog', {name: '添加工作区'})).toBeNull();
		});
	});

	it('drills into On This PC', async () => {
		const user = userEvent.setup();
		render(
			<WorkspaceAddButton recents={recents} onOpenPath={vi.fn(async () => undefined)} />,
		);
		await user.click(screen.getByRole('button', {name: '添加工作区'}));
		await user.click(screen.getByRole('button', {name: 'On This PC'}));
		expect(await screen.findByText('On This PC')).toBeTruthy();
		expect(await screen.findByText('D:\\lea\\claude')).toBeTruthy();
		expect(screen.getByRole('button', {name: 'Browse...'})).toBeTruthy();
	});
});
