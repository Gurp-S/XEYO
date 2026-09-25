/**
 * FilesChanged.test.ts — 「改动列表」点开的差异面板不得把读不出说成"没有内容"。
 *
 * 真实缺陷：gitFileDiff 失败时旧代码把 diff 置空后照常 openReview，
 * 面板于是显示一个空白 diff —— 用户看到的事实是"这个改动没有内容"，
 * 而真相是"服务端/校验没能给出差异"。同一处还有三种成功状态（binary / unchanged / none）
 * 也没有文本差异可显示，各自含义不同，不能都渲染成空白。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {gitFileDiff} from '@/lib/api';
import {toast} from '@/lib/toast';
import {useChatStore} from '@/stores/chatStore';
import {useExplorerStore} from '@/stores/explorerStore';
import {openChangedReview, reviewGapNote} from './FilesChanged';

vi.mock('@/lib/api', () => ({gitFileDiff: vi.fn()}));
vi.mock('@/lib/toast', () => ({toast: {error: vi.fn(), info: vi.fn()}}));
vi.mock('@/stores/chatStore', () => ({useChatStore: {getState: vi.fn()}}));
vi.mock('@/stores/explorerStore', () => ({useExplorerStore: {getState: vi.fn()}}));

const openReview = vi.fn();
const file = {path: 'a.ts', name: 'a.ts', add: 1, del: 0} as const;

beforeEach(() => {
	vi.clearAllMocks();
	vi.mocked(useChatStore.getState).mockReturnValue({
		spaces: [{id: 'sp1', rootPath: 'D:/proj'}],
		activeSpaceId: 'sp1',
	} as never);
	vi.mocked(useExplorerStore.getState).mockReturnValue({openReview} as never);
});

describe('reviewGapNote', () => {
	it('有正文时不需要说明', () => {
		expect(reviewGapNote('diff', true)).toBe('');
		expect(reviewGapNote('binary', true)).toBe('');
	});

	it('三种"读到了但没有文本差异"的状态各有自己的说法', () => {
		expect(reviewGapNote('binary', false)).toMatch(/二进制/);
		expect(reviewGapNote('unchanged', false)).toMatch(/相对 HEAD 没有文本差异/);
		expect(reviewGapNote('none', false)).toMatch(/不是 Git 仓库/);
	});
});

describe('openChangedReview', () => {
	it('拿到差异正文时照常打开面板，且不提示', async () => {
		vi.mocked(gitFileDiff).mockResolvedValue({kind: 'diff', diff: '@@ -1 +1 @@\n-x\n+y\n'} as never);
		await openChangedReview(file as never);
		expect(openReview).toHaveBeenCalledWith(
			{
				path: 'a.ts',
				name: 'a.ts',
				diff: '@@ -1 +1 @@\n-x\n+y\n',
				source: 'workspace',
			},
			{revealWorkspace: false},
		);
		expect(toast.info).not.toHaveBeenCalled();
		expect(toast.error).not.toHaveBeenCalled();
	});

	it('读不出差异时报错，不打开一个空面板', async () => {
		vi.mocked(gitFileDiff).mockRejectedValue(new Error('读取文件差异：kind=diff 但差异正文不在回执里'));
		await openChangedReview(file as never);
		expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('读不出 a.ts 的差异'));
		expect(openReview).not.toHaveBeenCalled();
	});

	it('二进制文件说清是二进制，而不是留一个空白面板', async () => {
		vi.mocked(gitFileDiff).mockResolvedValue({kind: 'binary', diff: null} as never);
		await openChangedReview(file as never);
		expect(toast.info).toHaveBeenCalledWith(expect.stringContaining('二进制'));
		expect(openReview).not.toHaveBeenCalled();
	});

	it('非仓库回执说"读不出差异"，不假装改动是空的', async () => {
		vi.mocked(gitFileDiff).mockResolvedValue({kind: 'none', diff: null} as never);
		await openChangedReview(file as never);
		expect(toast.info).toHaveBeenCalledWith(expect.stringContaining('不是 Git 仓库'));
		expect(openReview).not.toHaveBeenCalled();
	});

	it('活动里已经带着 diff 正文时不额外请求后端', async () => {
		await openChangedReview({...file, diff: 'diff --git a/a.ts b/a.ts'} as never);
		expect(gitFileDiff).not.toHaveBeenCalled();
		expect(openReview).toHaveBeenCalledWith(
			expect.objectContaining({
				diff: 'diff --git a/a.ts b/a.ts',
				source: 'recorded',
			}),
			{revealWorkspace: false},
		);
	});
});
