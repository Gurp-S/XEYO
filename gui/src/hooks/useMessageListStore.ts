import {useShallow} from 'zustand/react/shallow';
import type {MultiAgentTaskView} from '@/lib/api';
import {streamSignalsEnabled} from '@/lib/streamSignal';
import {
	selectActiveSessionStream,
	sessionStreamActive,
} from '@/lib/sessionStreams';
import type {ChatMessage} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {useChatUiStore} from '@/stores/chatUiStore';
import {useSwitchLag} from '@/stores/chat/switchLag';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';

const EMPTY_MESSAGES: ChatMessage[] = [];
const NO_AGENT_TASKS: MultiAgentTaskView[] = [];

export type MessageListStoreInputs = {
	smoothness: boolean;
	model: string;
	messages: ChatMessage[];
	/** 乐观切换：activeId 已就位但消息仍在后台装载（冷会话）。 */
	messagesPending: boolean;
	agentTasks: MultiAgentTaskView[];
	activeId: string | null;
	activeSessionArchived: boolean;
	viewingStream: boolean;
	isLoading: boolean;
	streamingSignal: boolean;
	streamingText: string;
	statusText: string;
	reasoningText: string;
	thoughtStartedAt: number | null;
	stopGeneration: () => void;
	anyStreaming: boolean;
	emptyQuipSeq: number;
	activeSpaceId: string;
	spaces: ReturnType<typeof useChatStore.getState>['spaces'];
};

type MessageListPropsSlice = {
	messages?: ChatMessage[];
	streamingText?: string;
	isLoading?: boolean;
	statusText?: string;
	agentTasks?: MultiAgentTaskView[];
};

export function useMessageListStore(
	props: MessageListPropsSlice,
): MessageListStoreInputs {
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const model = useSettingsStore(s => s.model);

	/* 信号直更路径（VITE_XY_STREAM_SIGNALS=1）：流式尾巴由 streamingTextSignal
	   直接更新单个文本节点，store 的 streamingShown 在这条路径下没有任何消费者
	   （见下方 streamingSignal / streamingText 的同一判据）。原先它仍进快照 →
	   每个 token 都让 useShallow 判不等 → 整棵 MessageList（含 VirtualRoundList
	   全部挂载轮）每 token 重渲一次。这里只在尾巴确实由信号渲染时不订阅该字段：
	   订阅值与不订阅值在任何时刻至多一边被读到，可见结果逐帧相同。
	   判据与 isLoading 完全同源（props.isLoading 优先），drain 阶段
	   （isLoading 假、draining 真）依旧走 store 路径，打字机不受影响。 */
	const signalMode = streamSignalsEnabled && props.streamingText === undefined;
	// 切会话首帧先按旧会话渲染（覆盖层盖着），下一帧追平 —— 见 chat/switchLag。
	const lagState = useSwitchLag();

	// 将所有选中字段拍平——嵌套对象会破坏 useShallow（每次
	// 调用产生新引用 → React useSyncExternalStore 死循环）。
	const {
		activeId,
		activeSessionArchived,
		storeMessages,
		storeMessagesPending,
		storeAgentTasks,
		stopGeneration,
		emptyQuipSeq,
		activeSpaceId,
		spaces,
		viewingStream,
		streamingShown,
		streamIsLoading,
		streamDraining,
		statusTextRaw,
		reasoningTextRaw,
		thoughtStartedAtRaw,
		anyStreaming,
	} = useChatUiStore(
		useShallow(s => {
			const id =
				lagState.lagging && lagState.displayed
					? lagState.displayed
					: s.activeId;
			const stream = selectActiveSessionStream(s);
			const viewing = Boolean(id && sessionStreamActive(s, id));
			/* 与下方 streamingSignal 严格同一判据（props.isLoading 优先）：
			   为真时尾巴由信号渲染，streamingShown 在本快照无人读取。 */
			const signalDriven =
				signalMode &&
				viewing &&
				Boolean(
					props.isLoading ?? (viewing && (stream.isLoading || stream.draining)),
				);
			return {
				activeId: id,
				activeSessionArchived: Boolean(
					id && s.sessions.some(session => session.id === id && session.archived),
				),
				storeMessages: id
					? (s.messagesById?.[id] ?? EMPTY_MESSAGES)
					: EMPTY_MESSAGES,
				storeMessagesPending: Boolean(id && s.messagesLoadingIds?.[id]),
				storeAgentTasks: id
					? (s.multiAgentTasksBySession?.[id] ?? NO_AGENT_TASKS)
					: NO_AGENT_TASKS,
				stopGeneration: s.stopGeneration,
				emptyQuipSeq: s.emptyQuipSeq,
				activeSpaceId: s.activeSpaceId,
				spaces: s.spaces,
				viewingStream: viewing,
				streamingShown: signalDriven ? '' : stream.streamingShown,
				streamIsLoading: stream.isLoading,
				streamDraining: stream.draining,
				statusTextRaw: stream.statusText,
				reasoningTextRaw: stream.reasoningText,
				thoughtStartedAtRaw: stream.thoughtStartedAt,
				anyStreaming: id ? sessionStreamActive(s, id) : false,
			};
		}),
	);

	const messages = props.messages ?? storeMessages;
	const messagesPending =
		props.messages === undefined && storeMessagesPending;
	const agentTasks = props.agentTasks ?? storeAgentTasks;

	const storeLoading = streamIsLoading || streamDraining;
	const isLoading = props.isLoading ?? (viewingStream && storeLoading);
	const streamingSignal = signalMode && viewingStream && isLoading;
	const streamingText =
		props.streamingText ??
		(streamingSignal
			? '\u200b'
			: viewingStream
				? streamingShown
				: '');
	const statusText =
		props.statusText ?? (viewingStream ? statusTextRaw : '');
	const reasoningText = viewingStream ? reasoningTextRaw : '';
	const thoughtStartedAt = viewingStream ? thoughtStartedAtRaw : null;

	return {
		smoothness,
		model,
		messages,
		messagesPending,
		agentTasks,
		activeId,
		activeSessionArchived,
		viewingStream,
		isLoading,
		streamingSignal,
		streamingText,
		statusText,
		reasoningText,
		thoughtStartedAt,
		stopGeneration,
		anyStreaming,
		emptyQuipSeq,
		activeSpaceId,
		spaces,
	};
}

export type RoundStreamHostProps = {
	roundSettled: boolean;
	streamingSignal: boolean;
	thoughtStartedAt: number | null;
	workflowStatusText: string;
	latestTurnId: string | null;
};

/** 将流式 props 固定在最新轮次上，使 memo(RoundHost) 在流式输出期间跳过历史轮次。 */
export function roundStreamHostProps(
	roundIndex: number,
	latestRoundIndex: number,
	live: RoundStreamHostProps,
): RoundStreamHostProps {
	if (roundIndex === latestRoundIndex) {
		return live;
	}
	return {
		roundSettled: true,
		streamingSignal: false,
		thoughtStartedAt: null,
		workflowStatusText: '',
		latestTurnId: null,
	};
}

export function useMessageListRollbackStore() {
	return useChatUiStore(
		useShallow(s => ({
			activeSessionId: s.activeId,
		})),
	);
}
