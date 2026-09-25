/**
 * terminalReceipt.test.ts — 终端面板不得把"200 但读不出"印成读数。
 *
 * /v1/workspace/terminal/exec 的真失败走 HTTP 状态码，客户端于是从不看响应体。
 * 缺字段的 200 过去会：stdout 缺失 ⇒ 一条输出都不显示；
 * exit_code / elapsed_ms 缺失 ⇒ 面板印「退出码 — · undefinedms」；
 * truncated 缺失 ⇒ 读 truncated.stdout 当场抛，整条命令的结果被换成一行错误。
 * 形体取自 python/server/workspace_terminal.py::run_command 的真实返回。
 */
import {describe, expect, it, vi} from 'vitest';
import {execWorkspaceTerminal, parseTerminalResult} from '@/lib/api';

const good = {
	ok: true,
	cwd: 'D:/proj',
	command: 'git status',
	shell: 'windows_nt',
	exit_code: 0,
	stdout: 'On branch main\n',
	stderr: '',
	timed_out: false,
	truncated: {stdout: false, stderr: false},
	elapsed_ms: 128,
};

function stubJson(payload: unknown) {
	return vi.fn().mockResolvedValue({ok: true, status: 200, json: async () => payload});
}

describe('终端回执', () => {
	it('完整回执原样通过', () => {
		expect(parseTerminalResult(good)).toMatchObject({exit_code: 0, elapsed_ms: 128});
	});

	it('超时没有退出码（null）是合法事实', () => {
		expect(parseTerminalResult({...good, exit_code: null, timed_out: true})).toMatchObject({
			exit_code: null,
			timed_out: true,
		});
	});

	it('缺 stdout / stderr = 读不出，不是"命令没有输出"', () => {
		const {stdout: _drop, ...rest} = good;
		expect(() => parseTerminalResult(rest)).toThrow(/没有输出/);
	});

	it('缺 timed_out / elapsed_ms 会印成 undefinedms，必须拦', () => {
		expect(() => parseTerminalResult({...good, elapsed_ms: undefined})).toThrow(/elapsed_ms/);
		expect(() => parseTerminalResult({...good, timed_out: undefined})).toThrow(/timed_out/);
	});

	it('exit_code 是字符串（转型会印成假退出码）必须拦', () => {
		expect(() => parseTerminalResult({...good, exit_code: '0'})).toThrow(/exit_code/);
	});

	it('缺 truncated 标记 ⇒ 不能说输出是完整的', () => {
		expect(() => parseTerminalResult({...good, truncated: undefined})).toThrow(/truncated/);
		expect(() => parseTerminalResult({...good, truncated: {stdout: false}})).toThrow(/truncated/);
	});

	it('不是对象一律读不出', () => {
		for (const bad of [null, undefined, 'x', [], 0]) {
			expect(() => parseTerminalResult(bad)).toThrow(/回执不是对象/);
		}
	});
});

describe('客户端确实走了解析', () => {
	it('200 + 缺 stdout ⇒ 抛给终端面板的 catch', async () => {
		vi.stubGlobal('fetch', stubJson({ok: true, cwd: 'x', command: 'ls', shell: 'bash', exit_code: 0}));
		await expect(execWorkspaceTerminal('ls', 5, 'D:/proj')).rejects.toThrow(/没有输出/);
		vi.unstubAllGlobals();
	});

	it('200 + 缺 truncated ⇒ 抛而不是崩在渲染里', async () => {
		const {truncated: _drop, ...rest} = good;
		vi.stubGlobal('fetch', stubJson(rest));
		await expect(execWorkspaceTerminal('ls', 5, 'D:/proj')).rejects.toThrow(/truncated/);
		vi.unstubAllGlobals();
	});

	it('形状完整的回执仍然照旧返回（不拦真实返回）', async () => {
		vi.stubGlobal('fetch', stubJson(good));
		await expect(execWorkspaceTerminal('git status', 5, 'D:/proj')).resolves.toMatchObject({exit_code: 0});
		vi.unstubAllGlobals();
	});
});
