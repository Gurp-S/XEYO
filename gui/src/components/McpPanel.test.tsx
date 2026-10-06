/**
 * MCP 面板（composer ＋菜单弹层）的关闭配对。
 *
 * 同族弹层（审批模式/模型选择/＋菜单/任务角标/用量浮层/右键菜单）全部
 * Esc + 外点关闭；MCP 面板此前同缺两条 ⇒ 只能点它自己的 X，流式中按 Esc
 * 还会落到下层把回合停掉。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';

vi.mock('@/lib/api/mcp', () => ({
	fetchMcpStatus: vi.fn(async () => ({servers: []})),
	mcpOp: vi.fn(async () => ({ok: true})),
}));

import {McpPanel} from './McpPanel';

beforeEach(() => {
	vi.clearAllMocks();
});

afterEach(() => {
	cleanup();
});

describe('McpPanel 关闭配对', () => {
	it('Esc 关闭面板', () => {
		const onClose = vi.fn();
		render(<McpPanel open onClose={onClose} />);
		expect(screen.getByLabelText('关闭 MCP 面板')).toBeTruthy();

		fireEvent.keyDown(window, {key: 'Escape'});
		expect(onClose).toHaveBeenCalledTimes(1);
	});

	it('点击面板外关闭', () => {
		const onClose = vi.fn();
		render(<McpPanel open onClose={onClose} />);

		fireEvent.mouseDown(document.body);
		expect(onClose).toHaveBeenCalledTimes(1);
	});

	it('面板内点击不关闭', () => {
		const onClose = vi.fn();
		render(<McpPanel open onClose={onClose} />);

		fireEvent.mouseDown(screen.getByLabelText('搜索 MCP'));
		expect(onClose).not.toHaveBeenCalled();
	});
});
