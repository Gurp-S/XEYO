import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {MessageList} from './MessageList';

vi.stubGlobal('IntersectionObserver', undefined);

vi.mock('./MarkdownView', () => ({
	MarkdownView: ({content}: {content: string}) => (
		<div data-testid="md">{content}</div>
	),
}));

vi.mock('@/hooks/useStreamTypewriter', () => ({
	useStreamTypewriter: (t: string) => t,
	typewriterStep: () => 1,
}));

vi.mock('@/hooks/useDebounced', () => ({
	useDebounced: (v: unknown) => v,
}));

vi.mock('@/stores/chatStore', () => {
	const state = {
		activeId: 'sess-1',
		emptyQuipSeq: 0,
		activeSpaceId: 'space-1',
		spaces: [{id: 'space-1', name: 'XEYO code', rootPath: 'D:/x'}],
		sessionStreams: {} as Record<string, {
			streamingText: string;
			streamingShown: string;
			isLoading: boolean;
			statusText: string;
			reasoningText: string;
			thoughtStartedAt: number | null;
			abortRef: null;
			remoteStreaming: boolean;
			draining: boolean;
		}>,
		messagesById: {} as Record<string, unknown[]>,
		rollbackById: {} as Record<string, unknown>,
		previewRollback: async () => false,
		executeRollback: async () => undefined,
		resolveRollbackRecovery: async () => undefined,
		cancelRollback: () => undefined,
		stopGeneration: () => undefined,
	};
	const useChatStore = (sel?: (s: typeof state) => unknown) =>
		typeof sel === 'function' ? sel(state) : state;
	return {useChatStore};
});

const userMsg = (text: string, id = 'u1'): ChatMessage => ({
	id,
	role: 'user',
	text,
	createdAt: Date.now(),
});

const asstMsg = (text: string, id = 'a1'): ChatMessage => ({
	id,
	role: 'assistant',
	text,
	createdAt: Date.now(),
});

describe('MessageList dialogue rendering', () => {
	it('shows empty hero when no rows', () => {
		render(
			<MessageList
				messages={[]}
				streamingText=""
				isLoading={false}
				statusText=""
			/>,
		);
		expect(
			screen.getByText('在「XEYO code」里，我们要一起构建些什么呢？'),
		).toBeInTheDocument();
		expect(screen.getByTestId('empty-quip').textContent?.length).toBeGreaterThanOrEqual(
			15,
		);
	});

		it('shows user bubble text', () => {
			render(
				<MessageList
					messages={[userMsg('用户消息')]}
					streamingText=""
					isLoading={false}
					statusText=""
				/>,
			);
			expect(screen.getByText('用户消息')).toBeInTheDocument();
			expect(
				document.querySelector('[data-prompt-text="用户消息"]'),
			).toHaveClass('anim-rise');
		});

		it('shows an uploaded image in the sent user bubble', () => {
			const digest = 'b'.repeat(64);
			render(
				<MessageList
					messages={[{...userMsg('请描述图片'), mediaRefs: [`xeyo-media://${digest}`]}]}
					streamingText=""
					isLoading={false}
					statusText=""
				/>,
			);
			const image = screen.getByAltText('已发送图片');
			expect(image).toBeInTheDocument();
			expect((image as HTMLImageElement).src).toContain(`/v1/media/${digest}`);
		});

			it('opens the sent image thumbnail in a large preview on click', async () => {
			const user = userEvent.setup();
			const digest = 'c'.repeat(64);
			render(
				<MessageList
					messages={[{...userMsg('查看图片'), mediaRefs: [`xeyo-media://${digest}`]}]}
					streamingText=""
					isLoading={false}
					statusText=""
				/>,
			);

			const thumbnail = screen.getByRole('button', {name: '查看已发送图片'});
			expect(thumbnail).toHaveClass('aspect-square', 'rounded-xl');
			await user.click(thumbnail);
			expect(screen.getByRole('dialog', {name: '图片预览'})).toBeInTheDocument();
			expect(screen.getAllByAltText('已发送图片')).toHaveLength(2);
			await user.keyboard('{Escape}');
			expect(screen.queryByRole('dialog', {name: '图片预览'})).not.toBeInTheDocument();
		});

		it('does not replay rise on older rounds', () => {

		render(
			<MessageList
				messages={[
					userMsg('旧提示', 'u-old'),
					asstMsg('ok', 'a-old'),
					{
						id: 'u-new',
						role: 'user',
						text: '新提示',
						createdAt: Date.now(),
					},
				]}
				streamingText=""
				isLoading={false}
				statusText=""
			/>,
		);
		expect(document.querySelector('[data-prompt-text="旧提示"]')).not.toHaveClass(
			'anim-rise',
		);
		expect(document.querySelector('[data-prompt-text="新提示"]')).toHaveClass(
			'anim-rise',
		);
	});

	it('works without stream props', () => {
		render(<MessageList messages={[userMsg('仅消息')]} />);
		expect(screen.getByText('仅消息')).toBeInTheDocument();
	});

	it('shows streaming text with cursor path', () => {
		render(
			<MessageList
				messages={[userMsg('q')]}
				streamingText="正在生成…"
				isLoading={true}
				statusText=""
			/>,
		);
		expect(screen.getByText('q')).toBeInTheDocument();
		const liveProse = document.querySelector('.xy-streamdown-live');
		expect(liveProse?.textContent).toContain('正在生成…');
	});

	it('shows reasoning when loading without stream text', async () => {
		const {useChatStore} = await import('@/stores/chatStore');
		const state = useChatStore() as {
			sessionStreams: Record<string, {
				streamingText: string;
				streamingShown: string;
				isLoading: boolean;
				statusText: string;
				reasoningText: string;
				thoughtStartedAt: number | null;
				abortRef: null;
				remoteStreaming: boolean;
				draining: boolean;
			}>;
		};
		state.sessionStreams = {
			'sess-1': {
				streamingText: '',
				streamingShown: '',
				isLoading: true,
				statusText: 'thinking…',
				reasoningText: 'Planning next steps',
				thoughtStartedAt: Date.now(),
				abortRef: null,
				remoteStreaming: false,
				draining: false,
			},
		};
		render(<MessageList messages={[userMsg('q')]} />);
		expect(screen.getByText('Planning next steps')).toBeInTheDocument();
		state.sessionStreams = {};
	});

	it('renders long history without throw', () => {
		const messages = Array.from({length: 80}, (_, i) =>
			i % 2 === 0 ? userMsg(`u-${i}`, `u${i}`) : asstMsg(`a-${i}`, `a${i}`),
		);
		expect(() =>
			render(
				<MessageList
					messages={messages}
					streamingText="tail"
					isLoading={true}
					statusText=""
				/>,
			),
		).not.toThrow();
		expect(screen.getAllByText('u-0').length).toBeGreaterThan(0);
		const liveTail = document.querySelector('.xy-streamdown-live');
		expect(liveTail?.textContent).toContain('tail');
	});

	it('renders system error lines', () => {
		render(
			<MessageList
				messages={[
					userMsg('x'),
					{
						id: 'e1',
						role: 'system',
						text: '无法连接后端',
						createdAt: Date.now(),
					},
				]}
				streamingText=""
				isLoading={false}
				statusText=""
			/>,
		);
		expect(screen.getByText('无法连接后端')).toBeInTheDocument();
	});
});
