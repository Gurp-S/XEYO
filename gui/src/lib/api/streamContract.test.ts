/**
 * streamContract.test.ts — 流式契约的门（二）：前端侧双向对账。
 *
 * 事故原型（本轮审计实测）：
 * - 后端发 `steer_delivered` / `tool_progress`，前端 `parseSseBlock()` 没有分支
 *   ⇒ 帧静默消失，界面无报错、测试全绿；
 * - 前端留着 `multi_agent_result` / `multi_agent_status` 的解析分支，后端从来不发
 *   ⇒ 死代码掩盖"这条路根本没接"的判断；
 * - GUI 的 `ProviderId` 含 `anthropic`，后端请求体 Literal 少它 ⇒ 每轮 422。
 *
 * 真相来源是 `src/generated/streamContract.ts`（由后端导出，CI 用 --check 防过期）。
 */
/// <reference types="vite/client" />
import {describe, expect, it} from 'vitest';
import {
	ACCEPT_EVENT_KEYS,
	CHAT_BODY_ENUMS,
	STREAM_EVENT_TYPES,
} from '@/generated/streamContract';
import CORE_SRC from './core?raw';
import CHAT_STREAM_SRC from './chatStream?raw';
import SETTINGS_SRC from '../../stores/settingsStore?raw';

/** 前端 `parseSseBlock()` 里认识的帧名。 */
function parsedFrameTypes(src: string): Set<string> {
	const out = new Set<string>();
	for (const m of src.matchAll(/xy\.type === '([a-z_]+)'/g)) out.add(m[1]!);
	// 压缩帧按 phase 前缀匹配，不是逐字面量分支。
	if (/xy\.type\?\.startsWith\('context_compression_'\)/.test(src)) {
		out.add('context_compression_start');
		out.add('context_compression_complete');
	}
	return out;
}

/**
 * 「后端在发、前端暂时故意不接」的登记处。加一项必须写清为什么不接；
 * 空着才是常态——静默丢弃不允许。
 */
const DECLARED_BUT_NOT_PARSED: Record<string, string> = {};

/** 「前端有分支、后端从不发」的登记处（真死了就该删，留下必须给理由）。 */
const PARSED_BUT_NEVER_DECLARED: Record<string, string> = {
	multi_agent_result: '子代理结算改走 jobs/子会话投影，此分支待删（见 2026-09-21 联调审计）',
	multi_agent_status: '同上',
};

describe('流式帧契约 · 双向对账', () => {
	const parsed = parsedFrameTypes(CORE_SRC);
	const declared = new Set<string>(STREAM_EVENT_TYPES);

	it('扫描器自身没有烂掉（正则失配会让上面几条全绿）', () => {
		expect(parsed.size).toBeGreaterThanOrEqual(20);
		expect(declared.size).toBeGreaterThanOrEqual(20);
		// 任取两个必然存在的帧名，确认抠法有效。
		expect(parsed.has('permission_pending')).toBe(true);
		expect(parsed.has('ask_user_resolved')).toBe(true);
	});

	it('后端声明的每种帧，前端都有解析分支（或已登记理由）', () => {
		const missing = [...declared]
			.filter(t => !parsed.has(t) && !(t in DECLARED_BUT_NOT_PARSED))
			.sort();
		expect(missing, `前端未识别的帧名会被静默丢弃：${missing.join(', ')}`).toEqual([]);
	});

	it('前端解析的每种帧名，后端都声明会发（或已登记为待删）', () => {
		const dead = [...parsed]
			.filter(t => !declared.has(t) && !(t in PARSED_BUT_NEVER_DECLARED))
			.sort();
		expect(dead, `后端从不发的死分支：${dead.join(', ')}`).toEqual([]);
	});

	it('登记理由不得空转：登记的项必须真的还在漂移', () => {
		const staleDeclared = Object.keys(DECLARED_BUT_NOT_PARSED).filter(t =>
			parsed.has(t),
		);
		const staleDead = Object.keys(PARSED_BUT_NEVER_DECLARED).filter(
			t => !parsed.has(t) || declared.has(t),
		);
		expect(staleDeclared, '已接上的帧请从登记表里删掉').toEqual([]);
		expect(staleDead, '分支已不存在或后端已声明，登记要清').toEqual([]);
	});

	it('chatStream 的两条派发循环都覆盖 stream_gap', () => {
		// reattach 有洞时前端必须知道；只写一条循环 = 刷新路径仍然静默丢段。
		const hits = CHAT_STREAM_SRC.match(/ev\.kind === 'stream_gap'/g) ?? [];
		expect(hits.length).toBeGreaterThanOrEqual(2);
	});
});

/**
 * 忙时 202 受理体的门：后端发的键 ↔ 前端读的键。
 * 事故原型：引导回执不发 `message_id`（或前端不看 `steered`）⇒ 前端把它当普通
 * 排队，造出一张 queue_id 为空、DELETE 必 400 的删不掉幽灵卡。
 */
const ACCEPT_KEYS_NOT_READ: Record<string, string> = {
	queued: '恒为 true 的标记位；分流看 steered，进到这里就已确认是受理',
};
describe('忙时 202 受理体与后端同源', () => {
	const declared = new Set<string>([
		...ACCEPT_EVENT_KEYS.queued,
		...ACCEPT_EVENT_KEYS.steered,
	]);
	// 只抠 202 分支体内：外层 `!res.ok || res.status === 202` 也含同一子串，
	// 按它切会得到 32 字符的空区域（本门的假绿来源）。
	const REGION = (
		CHAT_STREAM_SRC.split('if (res.status === 202) {')[1] ?? ''
	).split('handlers.onQueued?.(')[0];
	const read = new Set<string>(
		[...REGION.matchAll(/\bq\.([a-z_]+)/g)].map(m => m[1]!),
	);

	it('扫描器自身没有烂掉（区域抠飞会让本门假绿）', () => {
		expect(REGION.length).toBeGreaterThan(120);
		expect(read.has('steered')).toBe(true);
		expect(read.has('queue_id')).toBe(true);
		expect(read.size).toBeGreaterThanOrEqual(4);
	});

	it('前端读的每个键，后端都声明会发', () => {
		const phantom = [...read].filter(k => !declared.has(k)).sort();
		expect(phantom, `后端受理体从不发的键：${phantom.join(', ')}`).toEqual([]);
	});

	it('后端声明的每个键，前端都读（或写明为什么不读）', () => {
		const unused = [...declared]
			.filter(k => !read.has(k) && !(k in ACCEPT_KEYS_NOT_READ))
			.sort();
		expect(unused, `发了但没人看的受理体键：${unused.join(', ')}`).toEqual([]);
	});

	it('引导与排队靠 steered 分流（不看它就都走排队 = 幽灵卡）', () => {
		expect(/q\.steered\s*===\s*true/.test(REGION)).toBe(true);
	});

	it('登记理由不得空转：一旦读了就要从登记表删掉', () => {
		const stale = Object.keys(ACCEPT_KEYS_NOT_READ).filter(k => read.has(k));
		expect(stale, `已读取但仍登记为不发：${stale.join(', ')}`).toEqual([]);
	});
});

describe('请求体枚举与后端同源', () => {
	const guiProviderUnion = (
		readTypeAlias(SETTINGS_SRC, 'ProviderId') ?? ''
	)
		.split('|')
		.map(s => s.trim().replace(/^'|'$/g, ''))
		.filter(Boolean);

	it('GUI 能选的 provider 后端都收（少一个取值 = 一发消息就 422）', () => {
		const backend = new Set<string>(CHAT_BODY_ENUMS.provider);
		const rejected = guiProviderUnion.filter(p => !backend.has(p));
		expect(rejected, `后端 Literal 拒收：${rejected.join(', ')}`).toEqual([]);
	});

	it('agent_mode / output_mode / code_mode 的 GUI 取值也在后端枚举内', () => {
		const modes = new Set<string>(CHAT_BODY_ENUMS.agent_mode);
		expect(['agent', 'plan', 'ask'].every(m => modes.has(m))).toBe(true);
		const out = new Set<string>(CHAT_BODY_ENUMS.output_mode);
		expect(['lite', 'full', 'ultra'].every(m => out.has(m))).toBe(true);
	});
});

/** 从 TS 源里抠出 `export type Name = 'a' | 'b';` 的字面量联合。 */
function readTypeAlias(src: string, name: string): string | null {
	const re = new RegExp(`export type ${name} = ([^;]+);`);
	const m = re.exec(src);
	return m ? m[1]! : null;
}

/**
 * 「解析了没人接」的门：core.ts 声明的每个 handler 槽，store 侧必须真的实现。
 * 实测到 tool_progress / task_state_changed / llm_retry* 是"chatStream 派发了，
 * 但没有任何 store 提供该回调"⇒ 帧被 optional-call 静默吞掉，不报错也不告警。
 */
import HELPERS_SRC from '../../stores/chat/preStoreHelpers?raw';
import RECOVERY_SRC from '../../stores/chat/streamRecoverySlice?raw';
import SEND_SRC from '../../stores/chat/streamSendSlice?raw';

const NOT_IMPLEMENTED: Record<string, string> = {
	onTaskState: '任务态靠轻量轮询兜：2026-09-21 联调审计 B 组待办',
};

describe('handler 实现对账 · 派发了必须有人接', () => {
	const STORE_SRC = [SEND_SRC, RECOVERY_SRC, HELPERS_SRC].join('\n');
	// 只扫 ChatStreamHandlers 体内：全文扫会把别处的函数参数误当成槽位。
	const HANDLERS_BODY = (
		CORE_SRC.split('export type ChatStreamHandlers = {')[1] ?? ''
	).split(String.fromCharCode(10) + '};')[0];
	const declared = [...new Set(
		[...HANDLERS_BODY.matchAll(/^	on([A-Z]\w*)\??:/gm)].map(m => 'on' + m[1]),
	)];

	it('handler 槽集合非空（正则烂掉会让本门假绿）', () => {
		expect(declared.length).toBeGreaterThanOrEqual(15);
		expect(declared).toContain('onSteerDelivered');
		expect(declared).toContain('onSteered');
		expect(declared).not.toContain('onActivity');
	});

	/** store 里是否实现了该 handler 槽（对象方法简写：行首缩进 + 名字 + 左括号）。 */
	const implemented = (name: string) =>
		new RegExp(`^\\s*${name}\\s*\\(`, 'm').test(STORE_SRC);

	it('每个槽位都有 store 实现或登记理由', () => {
		const orphan = declared.filter(n => !implemented(n)).filter(n => !(n in NOT_IMPLEMENTED)).sort();
		expect(orphan, `派发了但无人实现的槽位：${orphan.join(', ')}`).toEqual([]);
	});

	it('登记理由不得空转：一旦实现就要从登记表删掉', () => {
		const stale = Object.keys(NOT_IMPLEMENTED).filter(implemented);
		expect(stale, `已实现但仍登记为孤儿：${stale.join(', ')}`).toEqual([]);
	});
});
