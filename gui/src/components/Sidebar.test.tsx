import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {afterEach, beforeAll, describe, expect, it, vi} from 'vitest';
import {MemoryRouter} from 'react-router-dom';
import {DEFAULT_SPACE_ID, SIDE_SPACE_ID} from '@/lib/db';
import {EMPTY_SESSION_STREAM} from '@/lib/sessionStreams';
import type {ChatSession, ChatSpace} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {setAppNavigator} from '@/lib/appNav';
import {ContextMenuHost} from './ui/ContextMenu';
import {Sidebar} from './Sidebar';

/**
 * 侧栏逻辑回归（2026-09-28 bug 侧）。每条 it 对应一个已确认缺陷的编号，
 * 注释里写明「不修会怎样」——把这些断言删掉就等于把 bug 放回去。
 */

vi.mock('@/lib/api', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		fetchWorkspacePeers: vi.fn(async () => ({peers: []})),
		deleteServerSession: vi.fn(async () => true),
		archiveServerSession: vi.fn(async () => true),
		restoreServerSession: vi.fn(async () => true),
		renameServerSession: vi.fn(async () => true),
		interruptChat: vi.fn(async () => ({ok: true, message: 'not_running'})),
		loadServerSessionMessages: vi.fn(async () => []),
		streamChat: vi.fn(),
	};
});

vi.mock('@/lib/db', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@/lib/db')>();
	return {
		...actual,
		loadSpaces: vi.fn(async () => []),
		loadSessions: vi.fn(async () => []),
		loadMessages: vi.fn(async () => []),
		loadChatHistoryState: vi.fn(async () => null),
		loadRollbackState: vi.fn(async () => null),
		saveRollbackState: vi.fn(async () => undefined),
		clearRollbackState: vi.fn(async () => undefined),
		saveChatHistoryState: vi.fn(async () => undefined),
		clearChatHistoryState: vi.fn(async () => undefined),
		saveSession: vi.fn(async () => undefined),
		saveSpace: vi.fn(async () => undefined),
		replaceMessages: vi.fn(async () => undefined),
		upsertMessages: vi.fn(async () => undefined),
		patchMessages: vi.fn(async () => undefined),
		deleteSession: vi.fn(async () => undefined),
		deleteSpace: vi.fn(async () => undefined),
		deleteSpaceRecord: vi.fn(async () => undefined),
		markSessionDeleted: vi.fn(async () => undefined),
		markSpaceDeleted: vi.fn(async () => undefined),
		loadDeletedSessionIds: vi.fn(async () => new Set<string>()),
		loadDeletedSpaceIds: vi.fn(async () => new Set<string>()),
		loadDeletedSpacePaths: vi.fn(async () => new Set<string>()),
		clearSpacePathTombstone: vi.fn(async () => undefined),
		purgeTombstonedLocalRecords: vi.fn(async () => undefined),
		ensureDefaultSpace: vi.fn(async () => undefined),
	};
});

beforeAll(() => {
	// jsdom 未实现 <dialog>.showModal/close（删除二次确认要用）。
	HTMLDialogElement.prototype.showModal = function showModal(
		this: HTMLDialogElement,
	) {
		this.setAttribute('open', '');
	};
	HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
		this.removeAttribute('open');
	};
});

const T0 = 1_700_000_000_000;

function space(id: string, partial?: Partial<ChatSpace>): ChatSpace {
	return {
		id,
		name: id,
		rootPath: `D:\\${id}`,
		createdAt: T0,
		updatedAt: T0,
		...partial,
	};
}

function session(
	id: string,
	spaceId: string,
	title: string,
	updatedAt: number,
	partial?: Partial<ChatSession>,
): ChatSession {
	return {
		id,
		spaceId,
		title,
		createdAt: T0,
		updatedAt,
		...partial,
	};
}

function seed(opts: {
	spaces?: ChatSpace[];
	sessions?: ChatSession[];
	activeId?: string | null;
	collapsedSpaces?: Record<string, boolean>;
}) {
	const {spaces = [], sessions = [], activeId = null, collapsedSpaces = {}} = opts;
	useChatStore.setState({
		hydrated: true,
		sidebarOpen: true,
		spaces,
		sessions,
		activeId,
		activeSpaceId: spaces[0]?.id ?? DEFAULT_SPACE_ID,
		collapsedSpaces,
		messagesById: Object.fromEntries(sessions.map(s => [s.id, []])),
		historyById: {},
		sessionStreams: {},
		recoveryBySession: {},
	});
}

function mount(pathname: string) {
	window.history.replaceState({}, '', pathname);
	return render(
		<MemoryRouter initialEntries={[pathname]}>
			<Sidebar />
			<ContextMenuHost />
		</MemoryRouter>,
	);
}

/** 展开「工作区」分组（默认收起，会话树不渲染）。 */
async function expandWorkspaces() {
	const button = await screen.findByRole('button', {name: '工作区'});
	if (button.getAttribute('aria-expanded') !== 'true') fireEvent.click(button);
}

function rowOf(title: string): HTMLElement {
	const label = screen.getByText(title);
	const row = label.closest('li');
	if (!row) {
		throw new Error(`未找到会话行：${title}`);
	}
	return row as HTMLElement;
}

/** 打开某条会话的三点菜单（归档态与常态的 aria-label 不同）。 */
async function openRowMenu(title: string) {
	const row = rowOf(title);
	const button =
		row.querySelector('button[aria-label="已归档对话操作"]') ??
		row.querySelector('button[aria-label="对话操作"]');
	if (!button) {
		throw new Error(`会话行 ${title} 没有操作按钮`);
	}
	fireEvent.click(button);
	return await screen.findByRole('menu');
}

async function runMenuItem(title: string, item: string) {
	const menu = await openRowMenu(title);
	// 菜单项动作跑完后 ContextMenu 在 microtask 里关闭 → 一并等进 act。
	await act(async () => {
		fireEvent.click(within(menu).getByRole('menuitem', {name: item}));
		await Promise.resolve();
	});
}

async function acceptDeleteDialog() {
	const dialog = await waitFor(() => {
		// The previous dialog may still be exiting; accept the newest modal.
		const d = Array.from(document.querySelectorAll('dialog')).at(-1);
		if (!d) {
			throw new Error('未出现删除确认弹窗');
		}
		return d;
	});
	await act(async () => {
		fireEvent.click(dialog.querySelector('.xy-id-confirm') as HTMLButtonElement);
		await Promise.resolve();
	});
}

afterEach(() => {
	cleanup();
	setAppNavigator(null);
});

describe('侧栏会话路由判定（bug #1）', () => {
	it('`/Side/<id>`（大写）下侧栏与 ChatPage 判定一致：点亮侧聊行而非主会话行', async () => {
		const sp = space('A');
		seed({
			spaces: [sp],
			sessions: [
				session('m1', 'A', '主会话甲', T0),
				session('s1', SIDE_SPACE_ID, '侧聊甲', T0),
			],
			activeId: 's1',
		});
		mount('/Side/s1');
		await expandWorkspaces();

		const sideRow = rowOf('侧聊甲');
		expect(sideRow.querySelector('.xy-session-on')).not.toBeNull();
		expect(rowOf('主会话甲').querySelector('.xy-session-on')).toBeNull();
	});
});

describe('页面视图下删除当前会话（bug #2）', () => {
	it('交接给同工作区的存活会话，而不是 removeSession 的盲兜底（它按数组顺序挑到别的工作区）', async () => {
		// sessions 数组顺序刻意把 B 工作区排在最前：不修时 removeSession 的
		// `sessions.find(!archived)` 兜底会选 b1，Esc 就落到另一个工作区。
		seed({
			spaces: [space('B'), space('A')],
			sessions: [
				session('b1', 'B', '乙区会话', T0 - 100),
				session('a1', 'A', '甲区当前', T0, {archived: true}),
				session('a2', 'A', '甲区另一', T0 - 1),
			],
			activeId: 'a1',
		});
		const navigated: string[] = [];
		setAppNavigator(to => navigated.push(to));
		mount('/usage');
		await expandWorkspaces();

		await runMenuItem('甲区当前', '删除对话');
		await acceptDeleteDialog();
		await waitFor(() =>
			expect(useChatStore.getState().sessions.map(s => s.id)).not.toContain('a1'),
		);
		expect(useChatStore.getState().activeId).toBe('a2');

		// 关掉页面视图的出口必须落在那条真实存活的会话上。
		navigated.length = 0;
		const {closePageView} = await import('@/lib/appNav');
		closePageView();
		expect(navigated).toEqual(['/c/a2']);
	});

	it('主会话没有同区接班人时宁可回到新对话态，也不把侧聊塞成当前会话', async () => {
		seed({
			spaces: [space('A')],
			sessions: [
				session('s1', SIDE_SPACE_ID, '侧聊甲', T0),
				session('a1', 'A', '甲区当前', T0, {archived: true}),
			],
			activeId: 'a1',
		});
		mount('/usage');
		await expandWorkspaces();

		await runMenuItem('甲区当前', '删除对话');
		await acceptDeleteDialog();
		await waitFor(() =>
			expect(useChatStore.getState().sessions.map(s => s.id)).not.toContain('a1'),
		);
		expect(useChatStore.getState().activeId).toBeNull();
	});
});

describe('页面视图下归档当前会话（bug #3）', () => {
	it('后续 selectSession 失败时不把出口留在已归档会话上（发射即忘会留下）', async () => {
		seed({
			spaces: [space('A')],
			sessions: [
				session('a1', 'A', '甲区当前', T0),
				session('a2', 'A', '甲区另一', T0 - 1),
			],
			activeId: 'a1',
		});
		// 只让「交接用的那一次选择」失败：真实 archiveSession 仍走服务端桩。
		const selectSession = vi.fn(async () => {
			throw new Error('选择会话失败');
		});
		useChatStore.setState({selectSession});
		mount('/usage');
		await expandWorkspaces();

		await runMenuItem('甲区当前', '归档对话');
		await waitFor(() =>
			expect(
				useChatStore.getState().sessions.find(s => s.id === 'a1')?.archived,
			).toBe(true),
		);
		expect(selectSession).toHaveBeenCalledWith('a2');
		expect(useChatStore.getState().activeId).toBeNull();
	});
});

describe('完成未回看微光集合（bug #9）', () => {
	it('归档掉的发光会话 id 会离开集合：恢复后不会凭空重新发光', async () => {
		seed({
			spaces: [space('A')],
			sessions: [
				session('a1', 'A', '甲区跑完', T0),
				session('a2', 'A', '甲区当前', T0 - 1),
			],
			activeId: 'a2',
		});
		useChatStore.setState({
			sessionStreams: {a1: {...EMPTY_SESSION_STREAM, isLoading: true}},
		});
		mount('/c/a2');
		await expandWorkspaces();

		// 跑完且不在看 → 点亮。
		act(() => useChatStore.setState({sessionStreams: {}}));
		await waitFor(() =>
			expect(
				rowOf('甲区跑完').querySelector('.xy-run-dot.is-done-unseen'),
			).not.toBeNull(),
		);

		await runMenuItem('甲区跑完', '归档对话');
		await waitFor(() =>
			expect(
				useChatStore.getState().sessions.find(s => s.id === 'a1')?.archived,
			).toBe(true),
		);
		// 等价于 restoreSession 成功后的会话状态（服务端调用与本缺陷无关）。
		act(() => {
			useChatStore.setState(s => ({
				sessions: s.sessions.map(x =>
					x.id === 'a1' ? {...x, archived: false} : x,
				),
			}));
		});
		await screen.findByText('甲区跑完');
		expect(rowOf('甲区跑完').querySelector('.is-done-unseen')).toBeNull();
	});
});

describe('会话可见列表（bug #10）', () => {
	it('按 updatedAt 排在 5 条之外的当前会话仍然渲染并带选中态', async () => {
		const sessions = Array.from({length: 7}, (_, i) =>
			session(`a${i}`, 'A', `会话${i}`, T0 - i * 1000),
		);
		seed({spaces: [space('A')], sessions, activeId: 'a6'});
		mount('/c/a6');
		await expandWorkspaces();

		const row = rowOf('会话6');
		expect(row.querySelector('.xy-session-on')).not.toBeNull();
		// 其余未选中项仍受 5 条上限约束（展开按钮少 1 条）。
		expect(screen.getByRole('button', {name: '展开其余 1 个会话'})).toBeTruthy();
		expect(screen.queryByText('会话5')).toBeNull();
	});
});

describe('首次使用空态（bug #12）', () => {
	it('0 工作区时不再显示搜索用的「无匹配结果」', async () => {
		seed({spaces: [], sessions: [], activeId: null});
		mount('/');
		await expandWorkspaces();
		expect(screen.queryByText('无匹配结果')).toBeNull();
		expect(screen.getByText(/还没有工作区/)).toBeTruthy();
	});
});

describe('短窗口下的导航区（bug #17）', () => {
	it('导航块不参与 flex 收缩，否则先被压掉的是最后的「诊断」', async () => {
		seed({spaces: [space('A')], sessions: [], activeId: null});
		mount('/');
		const newChat = await screen.findByRole('button', {name: /新对话/});
		const navBlock = newChat.parentElement;
		expect(navBlock?.className).toContain('shrink-0');
	});
});

describe('收合分组的空态（bug #29）', () => {
	it('分组收合时也要看得见「打开文件夹后开始」，不能被 0fr 树吞掉', async () => {
		seed({
			spaces: [space('A', {rootPath: ''})],
			sessions: [],
			activeId: null,
			collapsedSpaces: {A: true},
		});
		mount('/');
		await expandWorkspaces();
		const empty = await screen.findByText('打开文件夹后开始');
		expect(empty.closest('[aria-hidden="true"]')).toBeNull();
	});
});
