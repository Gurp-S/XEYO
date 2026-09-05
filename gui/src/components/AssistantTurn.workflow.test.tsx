/**
 * AssistantTurn 渲染级测试：展开后必须看到具体工具动词行。
 */
import {render, screen} from '@testing-library/react';
import {describe, expect, it, vi} from 'vitest';
import type {MultiAgentTaskView} from '@/lib/api';
import type {TurnItem} from '@/lib/groupTranscript';
import {AssistantTurn} from './AssistantTurn';
import {buildToolWorkflowFixture} from '@/lib/toolWorkflowFixture';

vi.mock('./MarkdownView', () => ({
	MarkdownView: ({content}: {content: string}) => (
		<div data-testid="md">{content}</div>
	),
}));

vi.mock('./StreamingMarkdown', () => ({
	StreamingMarkdown: ({
		text,
		final: isFinal,
	}: {
		text: string;
		final?: boolean;
	}) => (
		<div data-testid={isFinal ? 'md' : 'stream'}>{text}</div>
	),
}));

vi.mock('./AgentDoneBars', () => ({
	AgentDoneBars: ({tasks}: {tasks: MultiAgentTaskView[]}) => (
		<div data-testid="agent-bars">{tasks.map(t => t.uid).join(',')}</div>
	),
}));

vi.mock('./FilesChanged', () => ({
	FilesChanged: () => null,
}));

const sampleAgentTask = (): MultiAgentTaskView => ({
	uid: 't1',
	taskId: 'task-1',
	agentId: 'agent-1',
	desc: '执行多agent测试任务',
	status: 'running',
	batchAt: Date.now(),
});

describe('AssistantTurn workflow rendering', () => {
	it('settled: shows concrete tool verbs and final answer, hides旁白', () => {
		const items = buildToolWorkflowFixture('settled');
		render(
			<AssistantTurn
				turnId="turn-settled"
				items={items}
				active={false}
				roundSettled
				isLatestTurn
			/>,
		);

		expect(screen.getAllByText('Grepped').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Read').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Globbed').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Edited').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Created').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Ran').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Checked').length).toBeGreaterThan(0);

		const finalMd = screen.getByTestId('md');
		expect(finalMd).toHaveTextContent(/最小化按钮/);
		expect(finalMd).toHaveTextContent(/SquareStack/);

		expect(
			screen.queryByText(/让我先搜索相关的代码文件/),
		).not.toBeInTheDocument();
		expect(
			screen.queryByText(/现在让我查看 TitleBar/),
		).not.toBeInTheDocument();
	});

	it('live: shows Working path and running Reading step', () => {
		const items = buildToolWorkflowFixture('live');
		render(
			<AssistantTurn
				turnId="turn-live"
				items={items}
				active
				roundSettled={false}
				isLatestTurn
				thoughtStartedAt={Date.now() - 4000}
				thinking="继续核对 ActivityLog 展开行…"
			/>,
		);

		expect(screen.getAllByText('Reading').length).toBeGreaterThan(0);
		expect(screen.getByText('Working')).toBeInTheDocument();
		expect(
			screen.getByText(/让我先搜索相关的代码文件/),
		).toBeInTheDocument();
	});

	it('suppressActivity: only final prose when done-on layer owns tools', () => {
		const items = buildToolWorkflowFixture('settled');
		render(
			<AssistantTurn
				turnId="turn-final-only"
				items={items}
				active={false}
				roundSettled
				isLatestTurn
				suppressActivity
				visibleProseIds={new Set(['final-1'])}
			/>,
		);

		expect(screen.queryByText('Grepped')).not.toBeInTheDocument();
		expect(screen.getByText(/SquareStack/)).toBeInTheDocument();
		expect(screen.getByText(/最小化按钮/)).toBeInTheDocument();
	});

	it('live Agent: one card beside Delegating, not after Thought/prose', () => {
		const items: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'a1',
					role: 'assistant',
					text: '我将创建一个子agent来执行测试。',
					createdAt: 1,
					reasoningBefore: 'The user is asking to test the multi-agent tool.',
					thoughtMs: 1200,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 'tool-agent',
					name: 'Agent',
					input: JSON.stringify({
						task_id: 'task-1',
						desc: '执行多agent测试任务：创建一个简单的测试文件并验证功能',
					}),
					result: '',
					status: 'running',
					createdAt: 2,
				},
			},
		];
		render(
			<AssistantTurn
				turnId="turn-agent-live"
				items={items}
				active
				roundSettled={false}
				isLatestTurn
				agentTasks={[sampleAgentTask()]}
				thoughtStartedAt={Date.now() - 5000}
			/>,
		);

		expect(screen.getAllByText('Thought').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Delegating').length).toBeGreaterThan(0);
		expect(screen.getByText(/我将创建一个子agent/)).toBeInTheDocument();
		// Thought|prose|Delegating 交错时只能有一张卡，挂在 Delegating 旁
		expect(screen.getAllByTestId('agent-bars')).toHaveLength(1);
	});

	it('settled Agent: single card before final prose (suppressActivity)', () => {
		const items: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'final-agent',
					role: 'assistant',
					text: '子任务已完成。',
					createdAt: 3,
				},
			},
		];
		render(
			<AssistantTurn
				turnId="turn-agent-settled"
				items={items}
				active={false}
				roundSettled
				isLatestTurn
				suppressActivity
				visibleProseIds={new Set(['final-agent'])}
				agentTasks={[
					{...sampleAgentTask(), status: 'done', result: 'ok'},
				]}
			/>,
		);

		expect(screen.getAllByTestId('agent-bars')).toHaveLength(1);
		expect(screen.getByText(/子任务已完成/)).toBeInTheDocument();
	});

	it('serial Agent: one card per Delegated/Failed, not piled on first', () => {
		const items: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'a0',
					role: 'assistant',
					text: '先跑第一步',
					createdAt: 1,
					reasoningBefore: 'serial plan',
					thoughtMs: 500,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 'agent-1',
					name: 'Agent',
					input: JSON.stringify({
						task_id: 'step1',
						desc: '第一步：统计 JS',
					}),
					result: 'no js',
					status: 'done',
					createdAt: 2,
				},
			},
			{
				kind: 'assistant',
				message: {
					id: 'a1',
					role: 'assistant',
					text: '继续第二步',
					createdAt: 3,
					reasoningBefore: 'after step1',
					thoughtMs: 400,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 'agent-2',
					name: 'Agent',
					input: JSON.stringify({
						task_id: 'step2',
						desc: '第二步：统计 TS',
					}),
					result: 'err',
					status: 'error',
					createdAt: 4,
				},
			},
		];
		const tasks = [
			{
				...sampleAgentTask(),
				uid: 't1',
				taskId: 'step1',
				desc: '第一步：统计 JS',
				status: 'done' as const,
			},
			{
				...sampleAgentTask(),
				uid: 't2',
				taskId: 'step2',
				agentId: 'agent-2',
				desc: '第二步：统计 TS',
				status: 'failed' as const,
			},
		];
		render(
			<AssistantTurn
				turnId="turn-agent-serial"
				items={items}
				active
				roundSettled={false}
				isLatestTurn
				agentTasks={tasks}
			/>,
		);

		expect(screen.getAllByText('Delegated').length).toBeGreaterThan(0);
		expect(screen.getAllByText('Failed').length).toBeGreaterThan(0);
		const bars = screen.getAllByTestId('agent-bars');
		// 两段各一张，不能并成一块三张或堆在第一步后
		expect(bars).toHaveLength(2);
		expect(bars[0]).toHaveTextContent('t1');
		expect(bars[1]).toHaveTextContent('t2');
	});
});
