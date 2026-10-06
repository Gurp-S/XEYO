/**
 * remoteMirror 工具结果配对：并行同名工具必须按 id 归位。
 *
 * 本地路径早已按 toolUseId 配对（streamHelpers「按 toolUseId 用服务端结果覆盖本地」）；
 * 远端镜像在边界把 rec.id 丢了，只按"最后一个 running"猜 ⇒ 同名并行工具的
 * 结果会互换（完成顺序与调用顺序一致时必错）。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('@/lib/db', async () => {
	const actual = await vi.importActual<typeof import('@/lib/db')>('@/lib/db');
	return {
		...actual,
		replaceMessages: vi.fn(async () => undefined),
		saveSession: vi.fn(async () => undefined),
	};
});

import {remoteMirror} from './remoteMirrorSlice';
import {useChatStore} from '@/stores/chatStore';

const SID = 'sess_mirror_pair';

function seed() {
	useChatStore.setState({
		sessions: [
			{id: SID, spaceId: 'space_default', title: 't', createdAt: 1, updatedAt: 1},
		],
		messagesById: {[SID]: []},
		activeId: SID,
		sessionStreams: {},
	});
	remoteMirror.targetSid = SID;
}

const tools = () =>
	(useChatStore.getState().messagesById[SID] ?? []).filter(m => m.role === 'tool');

describe('remoteMirror 并行同名工具配对', () => {
	beforeEach(seed);

	it('两个同名工具结果按调用顺序回来：各归各卡（按 id，不许 LIFO 猜）', () => {
		const st = useChatStore.getState();
		st.applyRemoteToolCall('Read', {file_path: 'a.ts'}, 'tool-a');
		st.applyRemoteToolCall('Read', {file_path: 'b.ts'}, 'tool-b');
		// 完成顺序与调用顺序一致：a 的结果先回。
		st.applyRemoteToolResult('Read', 'OUT-A', false, 'tool-a');
		st.applyRemoteToolResult('Read', 'OUT-B', false, 'tool-b');

		const rows = tools();
		expect(rows).toHaveLength(2);
		expect(rows[0]?.toolUseId).toBe('tool-a');
		expect(rows[1]?.toolUseId).toBe('tool-b');
		expect(rows[0]?.text).toBe('OUT-A');
		expect(rows[1]?.text).toBe('OUT-B');
		expect(rows[0]?.toolStatus).toBe('done');
		expect(rows[1]?.toolStatus).toBe('done');
	});

	it('无 id 的记录退回旧口径（按名配最后一个在跑），结果不丢', () => {
		const st = useChatStore.getState();
		st.applyRemoteToolCall('Bash', {command: 'x'});
		st.applyRemoteToolResult('Bash', 'OUT-X');

		const rows = tools();
		expect(rows).toHaveLength(1);
		expect(rows[0]?.text).toBe('OUT-X');
		expect(rows[0]?.toolStatus).toBe('done');
	});
});
