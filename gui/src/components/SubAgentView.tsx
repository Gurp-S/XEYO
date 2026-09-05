import {memo, useEffect, useMemo, useState, type ReactNode} from 'react';
import type {MultiAgentTaskView} from '@/lib/api';
import type {AgentDetailMessage} from '@/lib/api';
import {postAgentInbox} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {MessageList} from './MessageList';

/** 稳定空列表：显式压制 MessageList 内部的任务卡片订阅。 */
const NO_AGENT_TASKS: MultiAgentTaskView[] = [];

/**
 * 子 Agent 视图（复用形态）：不弹遮罩、不加头部，直接把同一聊天区
 * 的「聊天记录」换成本会话该子 agent 的完整侧链对话。主视图时原样
 * 透传 children；进入子视图后渲染同一 MessageList 组件 — 头部/
 * Composer/侧栏等样式零变化，仅消息内容不同。
 *
 * 实时回放与主 agent 同款：运行中 SSE `multi_agent_delta` 帧把
 * token 级增量写进 chatStore.liveAgentTextById；渲染时按快照
 * assistant 文本总长对齐截尾（`buf.slice(snapLen)`）交给 MessageList
 * 的 streamingText —— 与主界面完全相同的流式逐字输出。任务落定由
 * finalizeAgentStream 刷终态快照并清空缓冲，无缝续接。
 *
 * 兜底轮询（1500ms）：覆盖不经 SSE 的直连 Agent 工具子任务，以及
 * 中途进入视图时的补齐；快照更新只补已落盘消息，与增量互不干扰。
 *
 * 返回由侧栏左箭头驱动（chatStore.agentViewStack 全局栈），
 * 此处不再放置返回按钮。
 */
export const SubAgentView = memo(function SubAgentView({
	children,
}: {
	children: ReactNode;
}) {
	const agentId = useChatStore(s => {
		const cur = s.agentViewStack[s.agentViewIndex];
		return cur && cur !== 'main' ? cur : null;
	});

	if (!agentId) {
		return <>{children}</>;
	}
	return <SubAgentTranscript key={agentId} agentId={agentId} />;
});

const SUBAGENT_POLL_MS = 1500;

const SubAgentTranscript = memo(function SubAgentTranscript({
	agentId,
}: {
	agentId: string;
}) {
	const sessionId = useChatStore(s => s.activeId);
	const detail = useChatStore(s =>
		sessionId ? s.agentTranscriptsById[`${sessionId}::${agentId}`] : undefined,
	);
	const liveText = useChatStore(
		s => (sessionId ? s.liveAgentTextById[`${sessionId}::${agentId}`] : undefined) ?? '',
	);
	const tasks = useChatStore(s =>
		sessionId ? s.multiAgentTasksBySession[sessionId] : undefined,
	);
	const ensureAgentTranscript = useChatStore(s => s.ensureAgentTranscript);

	const meta = useMemo(
		() => tasks?.find(t => t.agentId === agentId),
		[tasks, agentId],
	);

	// P2 follow-up inbox：向本 agent 投递 follow-up（park；settle 后同实例续跑）。
	const [followText, setFollowText] = useState('');
	const [sentNote, setSentNote] = useState('');
	const sendFollow = async () => {
		const t = followText.trim();
		if (!t || !sessionId) {
			return;
		}
		const r = await postAgentInbox(sessionId, agentId, t);
		if (r?.ok) {
			setFollowText('');
			setSentNote(
				r.deliver === 'running'
					? `已排队待该 agent 本轮完成后续跑（inbox ${r.inboxCount ?? 1}）`
					: '已挂起；重试该 agent 时会附带执行',
			);
		} else {
			setSentNote('投递失败');
		}
	};

	// 进入子视图即拉取一次；缓存里是运行中快照则强制刷新，避免旧态残留。
	useEffect(() => {
		if (!sessionId) return;
		void ensureAgentTranscript(sessionId, agentId, {
			force: detail?.status === 'running',
		});
		// 挂载/切换目标时执行一次即可；detail 刻意不入依赖。
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [sessionId, agentId, ensureAgentTranscript]);

	// 是否处于「运行中」：无任何状态信息时按运行中处理（轮询会自愈出真实状态）。
	const isLive =
		detail === undefined || detail === null
			? (meta?.status ?? 'running') === 'running'
			: detail.status === 'running';

	useEffect(() => {
		if (!sessionId || !isLive) return;
		const timer = setInterval(() => {
			void ensureAgentTranscript(sessionId, agentId, {force: true});
		}, SUBAGENT_POLL_MS);
		return () => clearInterval(timer);
	}, [sessionId, agentId, isLive, ensureAgentTranscript]);

	const messages: ChatMessage[] | null = useMemo(() => {
		if (!detail) {
			return null;
		}
		return detail.messages.map((message: AgentDetailMessage): ChatMessage => ({
			id: message.id,
			role: message.role,
			text: message.text,
			...(message.toolName !== undefined ? {toolName: message.toolName} : {}),
			...(message.toolInput !== undefined
				? {toolInput: message.toolInput}
				: {}),
			...(message.toolStatus !== undefined
				? {toolStatus: message.toolStatus}
				: {}),
			...(message.mediaRefs?.length ? {mediaRefs: message.mediaRefs} : {}),
			createdAt: message.createdAt,
		}));
	}, [detail]);

	// 快照 assistant 文本总长：增量缓冲超出该长度的部分才是「正在生成」的尾巴；
	// 服务端顺序回放保证 buf 与快照文本逐字一致，因此按长度对齐不会错位。
	const snapAssistantLen = useMemo(() => {
		if (!detail) return 0;
		let n = 0;
		for (const m of detail.messages) {
			if (m.role === 'assistant') n += m.text.length;
		}
		return n;
	}, [detail]);
	const streamingTail =
		isLive && liveText.length > snapAssistantLen
			? liveText.slice(snapAssistantLen)
			: '';

	if (!messages || messages.length === 0) {
		// 无提示占位：布局槽位保留；首字一旦到达即走同一条流式渲染路径。
		if (streamingTail) {
			return (
				<MessageList
					messages={[]}
					streamingText={streamingTail}
					isLoading={false}
					agentTasks={NO_AGENT_TASKS}
				/>
			);
		}
		return <div className="min-h-0 min-w-0 flex-1" />;
	}

	// 与主对话同构的渲染路径：isLoading 显式归零、streamingText 只喂本子 agent
	// 的增量尾巴；任务卡片显式置空，防止子视图轮次锚定挂上主会话的内联卡片。
	return (
		<div className="flex min-h-0 min-w-0 flex-1 flex-col">
			<div className="min-h-0 min-w-0 flex-1">
				<MessageList
					messages={messages}
					streamingText={streamingTail || ''}
					isLoading={false}
					agentTasks={NO_AGENT_TASKS}
				/>
			</div>
			<div className="flex items-center gap-2 border-t border-white/5 px-3 py-2">
				<input
					value={followText}
					onChange={e => setFollowText(e.target.value)}
					onKeyDown={e => {
						if (e.key === 'Enter' && !e.shiftKey) {
							e.preventDefault();
							void sendFollow();
						}
					}}
					placeholder={`向 ${agentId} 追加信息（回合结束后自动续跑）`}
					className="min-w-0 flex-1 rounded-md border border-white/10 bg-black/20 px-2 py-1 text-xs text-zinc-200 outline-none focus:border-amber-300/40"
				/>
				<button
					onClick={() => void sendFollow()}
					disabled={!followText.trim()}
					className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-zinc-300 hover:bg-white/10 disabled:opacity-40"
				>
					发送
				</button>
			</div>
			{sentNote ? <div className="px-3 pb-1 text-[11px] text-zinc-500">{sentNote}</div> : null}
		</div>
	);
});
