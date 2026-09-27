/**
 * diagContract.test.ts — 生产者枚举与界面标签表的对齐门。
 *
 * 锁的是结构，不是某一次措辞：`gui/src/generated/diagContract.ts` 由
 * `py -3.11 -m diagnostics.export_contract` 从诊断层**实际会发出的值**扫出来
 * （BOUNDARIES、RULES、add_gap 调用的原因码、fault_split 的 `_SHOWN_TEXT` 与
 * `PARTY_LABEL`、loss_chain 的状态常量与 verdict 字面量）。本文件要求界面的每张
 * 标签表都覆盖它。
 *
 * 为什么值得立这道门：同一份边界清单在 python 和 GUI 各手抄一份；缺项原因码
 * 曾两次靠"撞上了才补"（recovered_outside_window、not_found_in_full_file）。
 * 真实载荷冒烟测试里的机器码清单也是手抄的 —— 加了新码它不会红，
 * 用户会先看到 `unattributed_rows` 这种字面量。
 */
import {readdirSync, readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {describe, expect, it} from 'vitest';
import {
	DIAG_BOUNDARIES,
	DIAG_COVERAGE_SOURCES,
	DIAG_FACT_STATES,
	DIAG_FACT_VERDICTS,
	DIAG_GAP_REASONS,
	DIAG_PARTIES,
	DIAG_PAYLOAD_KEYS,
	DIAG_RULE_IDS,
	DIAG_SESSION_CONSTANT_GAPS,
	DIAG_SHOWN_STATES,
	DIAG_SHOWN_TEXTS,
} from '@/generated/diagContract';
import {
	BOUNDARY_ORDER,
	COVERAGE_SOURCE_LABEL,
	FACT_STATE_LABEL,
	FACT_STATE_TONE,
	FACT_VERDICT_TONE,
	GAP_REASON_LABEL,
	PARTY_LABEL,
	PARTY_TONE,
	SHOWN_LABEL,
	coverageSourceLabel,
	factStateLabel,
	gapReasonLabel,
} from './model';

function uniq(values: readonly string[]): string[] {
	return [...new Set(values)];
}

describe('诊断契约 · 生产者发得出，界面就必须说得出', () => {
	it('边界清单以生产者为正本，GUI 的 BOUNDARY_ORDER 逐项一致（含顺序与中文）', () => {
		expect(BOUNDARY_ORDER.map(b => b.name)).toEqual(DIAG_BOUNDARIES.map(b => b.name));
		for (const b of DIAG_BOUNDARIES) {
			const row = BOUNDARY_ORDER.find(x => x.name === b.name);
			expect(row, `界面缺边界 ${b.name}`).toBeDefined();
			expect(row?.label, `边界 ${b.name} 的中文与生产者不一致`).toBe(b.label);
		}
	});

	it('每个缺项原因码都有中文，且不是把机器名照抄回去', () => {
		expect(DIAG_GAP_REASONS.length).toBeGreaterThan(0);
		for (const gap of DIAG_GAP_REASONS) {
			const label = GAP_REASON_LABEL[gap.reason];
			expect(label, `界面缺原因码 ${gap.reason}（${gap.boundary}）`).toBeTruthy();
			expect(label).not.toContain(gap.reason);
			expect(gapReasonLabel(gap.reason)).not.toContain('未归类原因');
		}
	});

	it('送达状态的每个取值都有中文徽章说法', () => {
		expect(uniq(DIAG_SHOWN_STATES)).toEqual(DIAG_SHOWN_STATES);
		for (const state of DIAG_SHOWN_STATES) {
			const label = SHOWN_LABEL[state];
			expect(label, `界面缺送达状态 ${state}`).toBeTruthy();
			expect(label).not.toContain(state);
		}
	});

	it('徽章可以比后端正文短，但不许比它更肯定', () => {
		// 界面只读得到 fault.shown_to_model 这个枚举，措辞是这里现编的。编得比后端正文
		// 更肯定，读者就会把"读不出"当成结论：not_shown 曾被写成「未送达」，而后端
		// 刻意只说"不在留存的那一份发射投影里"（更早几枪的投影根本没落盘）。
		const assertTokens = ['未送达', '从未进入', '丢失'];
		// 反面自证：这些断言词里至少要有一个真的出现在某档后端正文里，否则门是空转的。
		expect(
			DIAG_SHOWN_STATES.some(s => assertTokens.some(t => (DIAG_SHOWN_TEXTS[s] ?? '').includes(t))),
			'断言词清单与后端正文完全不相交 —— 这道门抓不到任何东西',
		).toBe(true);
		for (const state of DIAG_SHOWN_STATES) {
			const label = SHOWN_LABEL[state] ?? '';
			const text = DIAG_SHOWN_TEXTS[state] ?? '';
			for (const token of assertTokens) {
				if (label.includes(token)) {
					expect(text, `徽章 ${state} 说了「${token}」，后端正文没有这么说`).toContain(token);
				}
			}
		}
		// 逐档钉住当前裁定：这两档的差别就是"过没过归属门"。
		expect(SHOWN_LABEL.not_shown).not.toContain('未送达');
		expect(SHOWN_LABEL.unprovable).not.toContain('未送达');
		expect(SHOWN_LABEL.folded_out).toContain('未送达');
	});

	it('采集覆盖表的每一档来源都有中文，界面也不留生产者不发的标签', () => {
		expect(uniq(DIAG_COVERAGE_SOURCES)).toEqual(DIAG_COVERAGE_SOURCES);
		expect(DIAG_COVERAGE_SOURCES.length).toBeGreaterThanOrEqual(8);
		for (const source of DIAG_COVERAGE_SOURCES) {
			const label = COVERAGE_SOURCE_LABEL[source];
			expect(label, `界面缺来源标签 ${source}`).toBeTruthy();
			expect(label).not.toContain(source);
			expect(coverageSourceLabel(source)).toBe(label);
		}
		for (const source of Object.keys(COVERAGE_SOURCE_LABEL)) {
			expect(DIAG_COVERAGE_SOURCES, `界面多了生产者不发的来源标签 ${source}`).toContain(source);
		}
	});

	it('定位链每一级状态都有中文说法与语气，且不留孤儿标签', () => {
		expect(DIAG_FACT_STATES.length).toBeGreaterThan(0);
		for (const state of DIAG_FACT_STATES) {
			const label = FACT_STATE_LABEL[state];
			expect(label, `界面缺定位链状态 ${state}`).toBeTruthy();
			expect(label).not.toContain(state);
			expect(factStateLabel(state)).toBe(label);
			expect(FACT_STATE_TONE[state], `定位链状态 ${state} 没有语气档`).toBeTruthy();
		}
		// 反向：界面表里不得留着生产者发不出的档位 —— 孤儿标签会把"真的漏了一档"
		// 混成"看起来挺全"，与手抄清单失效是同一个毛病。
		for (const state of Object.keys(FACT_STATE_LABEL)) {
			expect(DIAG_FACT_STATES, `界面多了生产者发不出的状态标签 ${state}`).toContain(state);
		}
		for (const state of Object.keys(FACT_STATE_TONE)) {
			expect(DIAG_FACT_STATES, `语气表里有生产者发不出的状态 ${state}`).toContain(state);
		}
	});

	it('定位链每条结论自己声明语气，新增一档不会静默降成中性', () => {
		expect(uniq(DIAG_FACT_VERDICTS)).toEqual(DIAG_FACT_VERDICTS);
		for (const verdict of DIAG_FACT_VERDICTS) {
			expect(FACT_VERDICT_TONE[verdict], `结论 ${verdict} 没有语气档`).toBeTruthy();
		}
		for (const verdict of Object.keys(FACT_VERDICT_TONE)) {
			expect(DIAG_FACT_VERDICTS, `语气表里有生产者不会发的结论 ${verdict}`).toContain(verdict);
		}
		// 严重度不得塌成一档：判不动、已定位到丢失、一路都在必须分得开
		expect(FACT_VERDICT_TONE['lost_before:emitted']).toBe('fail');
		expect(FACT_VERDICT_TONE.unknown).toBe('warn');
		expect(FACT_VERDICT_TONE.kept_through).not.toBe(FACT_VERDICT_TONE.unknown);
	});

	it('归属的每一档同时有说法和语气', () => {
		for (const party of DIAG_PARTIES) {
			expect(PARTY_LABEL[party], `界面缺归属 ${party}`).toBeTruthy();
			expect(PARTY_TONE[party], `归属 ${party} 没有语气档`).toBeTruthy();
		}
	});

	it('规则集非空且 id 不重复（规则名会原样出现在结论上）', () => {
		expect(DIAG_RULE_IDS.length).toBeGreaterThan(0);
		expect(uniq(DIAG_RULE_IDS)).toEqual([...DIAG_RULE_IDS]);
	});

	it('会话级缺项是"生产者会发"的子集，且每条都有中文说法', () => {
		// 界面按每行 scope 折叠；这张清单是 python 声明的会话级缺项的构建期镜像：
		// 它必须①非空（否则折叠逻辑在等一个永不命中的分支），②都出现在 gapReasons 里
		// （生产者确实发得出），③每条原因码都有中文（折叠后仍要说得清）。
		expect(DIAG_SESSION_CONSTANT_GAPS.length).toBeGreaterThan(0);
		const emitted = new Set(DIAG_GAP_REASONS.map(g => `${g.boundary}/${g.reason}`));
		for (const g of DIAG_SESSION_CONSTANT_GAPS) {
			expect(emitted.has(`${g.boundary}/${g.reason}`), `会话级缺项生产者发不出：${g.boundary}/${g.reason}`).toBe(true);
			const label = GAP_REASON_LABEL[g.reason];
			expect(label, `界面缺原因码 ${g.reason}`).toBeTruthy();
			expect(label).not.toContain(g.reason);
		}
	});
});

/**
 * 后端 payload 的每一个键都得有人读 —— 这一族今天的形状是「规则在跑、字段在给，
 * 界面上看不见」（责任划分那几栏今天逐个核对过是全读的，用量栏有 6 个键只活在
 * 后端自己拼的 statement 句子里）。豁免必须写明"这句话在人读面上由谁承担"，
 * 而且界面后来真的读了它时，这条豁免要变红逼人删掉。
 */
const UNREAD_OK: Record<string, string> = {
	'usage_summary.total_is_partial': 'report.py 把缺账/未计价/窗口残缺都拼进 usage_summary.statement，界面显示那句',
	'usage_summary.unpriced_attempts': '同上：「N 次尝试有用量行但行内没有可用价格」',
	'usage_summary.unpriced_keys': '同上；键列表留给导出与对账，不单独渲染',
	'usage_summary.usage_window_complete': '同上：「用量账本按尾窗读取，更早的账本行未纳入本次统计」',
	'usage_summary.usage_window_present': '同上：「本机没有可用的用量账本文件」',
	'fault.no_turn_records': '界面用本轮空态与 attribution 的未定桶表达，不再渲染一个布尔',
	// 以下 8 条是契约补全形状（report 顶层 / window）后才露出来的，逐条写明信息从哪到达读者：
	'report.evidence_rows': '步骤视图按「审计事件（本页/总）」说条数，用的是 events.length 与 event_total',
	'report.pin_count': '界面渲染 pins 列表本身，条数就是 pins.length，不再读第二个数',
	'window.rows_outside_window': '数字以正文形式进 note（_window_from_scan 的「更早的 N 行未覆盖」）',
	'window.rows_unparsable': '数字以正文形式进 note（_seal_window 的「N 行解不出 JSON 对象，已丢弃」）',
	'window.rows_unattributed': '数字以正文形式进 note（_seal_window 的「N 行不带本会话身份，未补值」）',
	'window.rows_capped': '数字以正文形式进 note（_seal_window 的「保留上限之外还有 N 行」）',
	'window.rows_other_session': '归到别的会话是正常过滤，不降级 complete，所以不写进正文（实测 fold_events 窗口 12 行属于这类）',
	'window.rows_other_turn': '归到本会话别的轮次同理：不是丢证据，读者看到的行数是本轮的',
};

const HERE = path.dirname(fileURLToPath(import.meta.url));

function consumerSources(): string {
	const parts: string[] = [];
	for (const name of readdirSync(HERE)) {
		if (!/\.(ts|tsx)$/.test(name) || name.includes('.test.')) {
			continue;
		}
		parts.push(readFileSync(path.join(HERE, name), 'utf8'));
	}
	parts.push(readFileSync(path.join(HERE, '..', '..', 'lib', 'api', 'diagnostics.ts'), 'utf8'));
	return parts.join('\n');
}

describe('诊断契约 · 后端给的字段界面必须接住', () => {
	it('payload 键全部有归属：被读过，或写明理由地豁免', () => {
		const src = consumerSources();
		const total = Object.values(DIAG_PAYLOAD_KEYS).reduce((n, keys) => n + keys.length, 0);
		// 反空转：清单为空 = 这道门什么都没看。
		expect(total).toBeGreaterThan(40);
		// 反向守卫之二：清单**缩水**也得红。以前只钉 5 档形状，报告顶层、原因条目、
		// 缺项、窗口、工具调用、模型请求全在棘轮外 —— 往那里加一个没人读的字段
		// 一句都不红（补全后立刻露出 8 个）。只数总键数抓不到"整档被删掉"。
		for (const group of [
			'finding',
			'evidence',
			'fault',
			'attribution',
			'usage_summary',
			'report',
			'cause',
			'gap',
			'window',
			'tool_call',
			'model_request',
		]) {
			expect(
				(DIAG_PAYLOAD_KEYS[group] ?? []).length,
				`契约的 ${group} 一档不见了：棘轮又盖不到整份载荷`,
			).toBeGreaterThan(0);
		}
		const unread: string[] = [];
		const stale: string[] = [];
		for (const [group, keys] of Object.entries(DIAG_PAYLOAD_KEYS)) {
			for (const key of keys) {
				const name = `${group}.${key}`;
				const read = new RegExp(`\\b${key}\\b`).test(src);
				if (!read && !(name in UNREAD_OK)) {
					unread.push(name);
				}
				if (read && name in UNREAD_OK) {
					stale.push(name);
				}
			}
		}
		expect(unread, `后端给了、界面从没读的键：${unread.join(', ')}`).toEqual([]);
		expect(stale, `这些豁免键界面已经在读了，请删掉豁免：${stale.join(', ')}`).toEqual([]);
	});

	it('一条发现的人读栏位逐个渲染（缺任何一栏都会把免责话术丢掉）', () => {
		const src = consumerSources();
		for (const key of DIAG_PAYLOAD_KEYS.finding) {
			expect(src.includes(key), `界面没读 finding.${key}`).toBe(true);
		}
	});
});
