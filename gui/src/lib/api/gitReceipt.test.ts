/**
 * gitReceipt.test.ts — Git 只读面板在"200 但读不出"时不得编造仓库状态。
 *
 * 这四个端点的真失败会走 HTTP 状态码，所以客户端过去完全不看响应体，
 * 直接 `as` 成结果类型。缺字段的 200 因此会被界面读成正面事实：
 * - Git 面板：`!status?.repo` ⇒「当前工作区不是 Git 仓库」；
 * - Git 面板：`repo=true` 且 clean/清单都不在 ⇒ 三个 StatusGroup 全渲染 null ⇒「没有任何改动」；
 * - 提交记录：`log.commits` 不在 ⇒ `commits.length` 当场抛，整块面板崩；
 * - 分支树：`branches` 不在 ⇒ 只剩当前分支；
 * - 差异面板：`kind=diff` 而 diff 不在 ⇒ 打开一个空 diff，看着像"改动是空的"。
 * 好形体取自 python/server/workspace_git.py 的真实返回，逐字段对照。
 */
import {describe, expect, it, vi} from 'vitest';
import {
	gitBranches,
	gitFileDiff,
	gitLog,
	gitStatus,
	parseGitBranches,
	parseGitFileDiff,
	parseGitLog,
	parseGitStatus,
} from '@/lib/api';

const dirtyStatus = {
	ok: true,
	repo: true,
	cwd: 'D:/proj',
	branch: 'main',
	head: '',
	clean: false,
	counts: {staged: 0, unstaged: 1, untracked: 0},
	staged: [],
	unstaged: [{path: 'a.ts', status: '修改', index: ' ', worktree: 'M'}],
	untracked: [],
};

function stubJson(payload: unknown) {
	return vi.fn().mockResolvedValue({ok: true, status: 200, json: async () => payload});
}

describe('Git 状态回执', () => {
	it('形状完整的 dirty 状态原样通过', () => {
		expect(parseGitStatus(dirtyStatus)).toMatchObject({repo: true, clean: false});
	});

	it('非仓库回执（producer 的 repo=false 分支）通过', () => {
		expect(parseGitStatus({ok: true, repo: false, cwd: 'D:/proj'})).toMatchObject({repo: false});
	});

	it('缺 repo = 读不出，不是"这个目录没有仓库"', () => {
		const {repo: _drop, ...rest} = dirtyStatus;
		expect(() => parseGitStatus(rest)).toThrow(/不代表这不是 Git 仓库/);
	});

	it('repo=true 而 clean 缺失 = 读不出，不是"工作区干净"', () => {
		const {clean: _drop, ...rest} = dirtyStatus;
		expect(() => parseGitStatus(rest)).toThrow(/clean/);
	});

	it('clean=false 但三个清单都不在 = 读不出，不是"没有改动"', () => {
		const {staged: _a, unstaged: _b, untracked: _c, ...rest} = dirtyStatus;
		expect(() => parseGitStatus(rest)).toThrow(/没有改动/);
	});

	it('clean=true 时空清单是自洽的，不该拦', () => {
		expect(
			parseGitStatus({ok: true, repo: true, cwd: 'x', branch: 'main', clean: true, counts: {staged: 0, unstaged: 0, untracked: 0}}),
		).toMatchObject({clean: true});
	});

	it('清单字段存在却不是数组 = 读不出（否则 entries.map 当场崩）', () => {
		expect(() => parseGitStatus({...dirtyStatus, unstaged: 'a.ts'})).toThrow(/unstaged/);
	});
});

describe('提交记录与分支回执', () => {
	const goodLog = {
		ok: true,
		repo: true,
		cwd: 'D:/proj',
		commits: [{hash: 'a'.repeat(40), short: 'aaaaaaa', author: 'dev', date: '2026-09-25 10:00', subject: '修一个缺陷'}],
	};

	it('完整提交列表通过，缺 commits 不得变成"暂无提交"', () => {
		expect(parseGitLog(goodLog)).toMatchObject({repo: true});
		const {commits: _drop, ...rest} = goodLog;
		expect(() => parseGitLog(rest)).toThrow(/没有提交/);
	});

	it('commits 里混进非提交条目（null / 字符串 / 缺字段）算读不出', () => {
		expect(() => parseGitLog({...goodLog, commits: [null]})).toThrow(/不是提交/);
		expect(() => parseGitLog({...goodLog, commits: ['aaaaaaa']})).toThrow(/不是提交/);
		expect(() => parseGitLog({...goodLog, commits: [{hash: 'x'}]})).toThrow(/不是提交/);
	});

	it('非仓库的 log 回执（commits=[]）通过', () => {
		expect(parseGitLog({ok: true, repo: false, cwd: 'D:/proj', commits: []})).toMatchObject({repo: false});
	});

	it('缺 branches 不得变成"只有当前分支"', () => {
		expect(parseGitBranches({ok: true, repo: true, cwd: 'x', current: 'main', branches: ['main']})).toMatchObject({
			current: 'main',
		});
		expect(() => parseGitBranches({ok: true, repo: true, cwd: 'x', current: 'main'})).toThrow(/只有当前分支/);
	});

	it('branches 里非字符串、current 类型不对都算读不出', () => {
		expect(() => parseGitBranches({ok: true, repo: true, cwd: 'x', branches: [null]})).toThrow(/branches/);
		expect(() => parseGitBranches({ok: true, repo: true, cwd: 'x', branches: ['main'], current: 1})).toThrow(/current/);
	});

	it('detached HEAD（current=null）与空分支列表是合法事实，不该拦', () => {
		expect(parseGitBranches({ok: true, repo: true, cwd: 'x', current: null, branches: []})).toMatchObject({
			current: null,
		});
	});
});

describe('单文件差异回执', () => {
	it('kind=diff 而差异正文不在 = 读不出，不是"改动是空的"', () => {
		expect(() => parseGitFileDiff({ok: true, repo: true, cwd: 'x', path: 'a.ts', kind: 'diff'})).toThrow(
			/改动是空的/,
		);
		expect(() => parseGitFileDiff({ok: true, repo: true, cwd: 'x', path: 'a.ts', kind: 'diff', diff: '   '})).toThrow(
			/改动是空的/,
		);
	});

	it('缺 kind = 不知道该文件算什么状态', () => {
		expect(() => parseGitFileDiff({ok: true, repo: true, cwd: 'x', path: 'a.ts'})).toThrow(/kind/);
	});

	it('binary / unchanged / none 允许没有差异正文', () => {
		expect(parseGitFileDiff({ok: true, repo: true, cwd: 'x', path: 'a.png', kind: 'binary', diff: null})).toMatchObject({
			kind: 'binary',
		});
		expect(parseGitFileDiff({ok: true, repo: true, cwd: 'x', path: 'a.ts', kind: 'unchanged', diff: ''})).toMatchObject({
			kind: 'unchanged',
		});
		expect(parseGitFileDiff({ok: true, repo: false, cwd: 'x', path: 'a.ts', kind: 'none', diff: null})).toMatchObject({
			kind: 'none',
		});
	});

	it('正常差异文本通过', () => {
		expect(
			parseGitFileDiff({
				ok: true,
				repo: true,
				cwd: 'x',
				path: 'a.ts',
				kind: 'diff',
				diff: 'diff --git a/a.ts b/a.ts\n@@ -1 +1 @@\n-x\n+y\n',
			}),
		).toMatchObject({kind: 'diff'});
	});
});

describe('客户端确实走了解析（不是转型完就 return）', () => {
	it('gitStatus：200 + repo=true 无 clean ⇒ 抛给面板的 catch', async () => {
		vi.stubGlobal('fetch', stubJson({ok: true, repo: true, cwd: 'D:/proj', branch: 'main'}));
		await expect(gitStatus('D:/proj')).rejects.toThrow(/clean/);
		vi.unstubAllGlobals();
	});

	it('gitLog：200 + 缺 commits ⇒ 抛而不是崩在渲染里', async () => {
		vi.stubGlobal('fetch', stubJson({ok: true, repo: true, cwd: 'D:/proj'}));
		await expect(gitLog(50, 'D:/proj')).rejects.toThrow(/没有提交/);
		vi.unstubAllGlobals();
	});

	it('gitBranches：200 + 缺 branches ⇒ 抛而不是显示"只有一个分支"', async () => {
		vi.stubGlobal('fetch', stubJson({ok: true, repo: true, cwd: 'D:/proj', current: 'main'}));
		await expect(gitBranches('D:/proj')).rejects.toThrow(/只有当前分支/);
		vi.unstubAllGlobals();
	});

	it('gitFileDiff：200 + kind=diff 无正文 ⇒ 抛给"退回文件视图"的 catch', async () => {
		vi.stubGlobal('fetch', stubJson({ok: true, repo: true, cwd: 'D:/proj', path: 'a.ts', kind: 'diff'}));
		await expect(gitFileDiff('a.ts', 'D:/proj')).rejects.toThrow(/改动是空的/);
		vi.unstubAllGlobals();
	});

	it('HTTP 非 200 仍按后端 detail 抛（校验器不该抢这条路径）', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue({ok: false, status: 503, json: async () => ({detail: 'git 未安装或不在 PATH 中'})}),
		);
		await expect(gitStatus('D:/proj')).rejects.toThrow(/git 未安装/);
		vi.unstubAllGlobals();
	});
});
