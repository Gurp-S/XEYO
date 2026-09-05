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

	// 将所有选中字段拍平——嵌套对象会破坏 useShallow（每次
	// 调用产生新引用 → React useSyncExternalStore 死循环）。
	const {
		activeId,
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
			const id = s.activeId;
			const stream = selectActiveSessionStream(s);
			const viewing = Boolean(id && sessionStreamActive(s, id));
			return {
				activeId: id,
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
				streamingShown: stream.streamingShown,
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

	const signalMode = streamSignalsEnabled && props.streamingText === undefined;
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
