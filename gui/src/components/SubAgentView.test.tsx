/**
 * SubAgentView.test.tsx — 侧链拉取失败不许是「永久空白」。
 *
 * ensureAgentTranscript 失败只把快照静默置 null（不抛）；而 done 态的子代理
 * 不进入轮询 ⇒ 打开侧链时一次网络抖动就得到一块无字无入口的空白面板，要退出
 * 重进才可能恢复（store 注释「轮询会自然覆盖」对 done 态不成立）。
 */
import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

const loadAgentDetail = vi.fn();
vi.mock('@/lib/api', async importOriginal => {
	const mod = await importOriginal<typeof import('@/lib/api')>();
	return {...mod, loadAgentDetail};
});

const {useChatStore} = await import('@/stores/chatStore');
const {SubAgentView} = await import('@/components/SubAgentView');

beforeEach(() => {
	loadAgentDetail.mockReset();
	useChatStore.setState({
		activeId: 's1',
		sessions: [{id: 's1', archived: false}],
		agentViewStack: ['main', 'ag1'],
		agentViewIndex: 1,
		agentTranscriptsById: {'s1::ag1': null},
		multiAgentTasksBySession: {
			s1: [{uid: 'ag1', taskId: 't1', agentId: 'ag1', desc: '整理清单', status: 'done'}],
		},
	} as never);
});

afterEach(() => {
	cleanup();
});

describe('SubAgentView 侧链读取失败态', () => {
	it('失败时不空白：给出可读提示与重试入口', async () => {
		loadAgentDetail.mockResolvedValue(null);
		render(<SubAgentView>{null}</SubAgentView>);

		expect(await screen.findByText(/暂不可读/)).toBeTruthy();
		expect(screen.getByRole('button', {name: /重试/})).toBeTruthy();
	});

	it('重试成功后背回侧链正文', async () => {
		loadAgentDetail
			.mockResolvedValueOnce(null)
			.mockResolvedValueOnce({
				status: 'done',
				messages: [{id: 'm1', role: 'assistant', text: '侧链正文回执', createdAt: 1}],
			});
		render(<SubAgentView>{null}</SubAgentView>);

		await screen.findByText(/暂不可读/);
		await userEvent.click(screen.getByRole('button', {name: /重试/}));

		expect(await screen.findByText('侧链正文回执')).toBeTruthy();
	});
});
