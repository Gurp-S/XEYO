/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec m1a: types，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 * 代码块自 components/MessageList.tsx 原样迁移，行为不变。
 */
import {
	type TranscriptBlock,
} from '@/lib/groupTranscript';
import {
	type MultiAgentTaskView,
} from '@/lib/api';
import {
	type ChatMessage,
} from '@/lib/types';

export type MessageListProps = {
	/** 测试可注入；页面上由本组件订阅 store，ChatPage 不因 token 重绘预览。 */
	messages?: ChatMessage[];
	streamingText?: string;
	isLoading?: boolean;
	statusText?: string;
	/** 测试可注入的多 Agent 任务；页面路径由本组件订阅 store。 */
	agentTasks?: MultiAgentTaskView[];
};

/** 一个用户提示 + 后续轮次，直到下一个用户。 */
export type Round = {
	id: string;
	user?: ChatMessage;
	rest: TranscriptBlock[];
	/** 锚定到本轮的子 Agent 任务（多 Agent 模式内联卡片）。 */
	agentTasks: MultiAgentTaskView[];
};
