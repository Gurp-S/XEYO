import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {useChatStore} from '@/stores/chatStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {useSettingsStore} from '@/stores/settingsStore';
import type {ChatMessage} from '@/lib/types';
import {WorkbenchChanges} from './WorkbenchChanges';
import {useWorkbenchChanges} from './useWorkbenchChanges';

vi.unmock('@/stores/settingsStore');
const project = vi.hoisted(() => vi.fn(() => []));
vi.mock('@/lib/workbenchChangesProjection', () => ({createWorkbenchChangesProjection: () => project}));
vi.mock('@/lib/workspaceGit', () => ({readWorkspaceGit: vi.fn(), workspaceGitFiles: () => []}));
vi.mock('../FilesChanged', () => ({openChangedReview: vi.fn()}));
const message = (text: string): ChatMessage => ({id: 'u', role: 'user', text, createdAt: 1});
function ResourcePreview() { useWorkbenchChanges(); return null; }
function updateMessages(count = 100) {
	for (let i = 0; i < count; i++) act(() => useChatStore.setState({messagesById: {s: [message(String(i))]}}));
}
beforeEach(() => {
	useChatStore.setState({activeId: 's', activeSpaceId: 'w', spaces: [], messagesById: {s: [message('initial')]}});
	useWorkspaceStore.setState({open: true});
	useSettingsStore.setState({settingsModalOpen: false});
	project.mockClear();
});
afterEach(cleanup);

describe('工作区计算按可见范围运行', () => {
	it.each(['closed', 'settings', 'usage'])('%s 时不计算，重新显示后使用最新消息', kind => {
		if (kind === 'closed') useWorkspaceStore.setState({open: false});
		if (kind === 'settings') useSettingsStore.setState({settingsModalOpen: true});
		const view = render(<MemoryRouter initialEntries={[kind === 'usage' ? '/usage' : '/']}><ResourcePreview /></MemoryRouter>);
		project.mockClear();
		updateMessages();
		console.info(`PERF workbench ${kind} computations for 100 updates:`, project.mock.calls.length);
		expect(project).not.toHaveBeenCalled();
		if (kind === 'usage') {
			view.unmount();
			render(<MemoryRouter><ResourcePreview /></MemoryRouter>);
		} else act(() => {
			useWorkspaceStore.setState({open: true});
			useSettingsStore.setState({settingsModalOpen: false});
		});
		expect(project).toHaveBeenLastCalledWith([message('99')], undefined);
	});
	it('切到 Git 时不解析对话，切回本轮恢复', () => {
		render(<MemoryRouter><WorkbenchChanges /></MemoryRouter>);
		fireEvent.click(screen.getByRole('button', {name: 'Git'}));
		project.mockClear();
		updateMessages();
		console.info('PERF workbench Git computations for 100 updates:', project.mock.calls.length);
		expect(project).not.toHaveBeenCalled();
		fireEvent.click(screen.getByRole('button', {name: '本轮'}));
		expect(project).toHaveBeenLastCalledWith([message('99')], undefined);
	});
});
