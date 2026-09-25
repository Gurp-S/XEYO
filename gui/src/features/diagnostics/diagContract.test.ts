/**
 * diagContract.test.ts — 生产者枚举与界面标签表的对齐门。
 *
 * 锁的是结构，不是某一次措辞：`gui/src/generated/diagContract.ts` 由
 * `py -3.11 -m diagnostics.export_contract` 从诊断层**实际会发出的值**扫出来
 * （BOUNDARIES、RULES、add_gap 调用的原因码、fault_split 的 `_SHOWN_TEXT` 与
 * `PARTY_LABEL`）。本文件要求界面的每张标签表都覆盖它。
 *
 * 为什么值得立这道门：同一份边界清单在 python 和 GUI 各手抄一份；缺项原因码
 * 曾两次靠"撞上了才补"（recovered_outside_window、not_found_in_full_file）。
 * 真实载荷冒烟测试里的机器码清单也是手抄的 —— 加了新码它不会红，
 * 用户会先看到 `unattributed_rows` 这种字面量。
 */
import {describe, expect, it} from 'vitest';
import {
	DIAG_BOUNDARIES,
	DIAG_GAP_REASONS,
	DIAG_PARTIES,
	DIAG_RULE_IDS,
	DIAG_SHOWN_STATES,
} from '@/generated/diagContract';
import {
	BOUNDARY_ORDER,
	GAP_REASON_LABEL,
	PARTY_LABEL,
	PARTY_TONE,
	SHOWN_LABEL,
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
});
