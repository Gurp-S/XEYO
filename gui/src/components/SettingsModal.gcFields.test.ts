/**
 * 回溯清理设置的输入解析 —— "留空" 与 "写错了" 必须是两条不同的路。
 *
 * 旧实现把不可解析的输入折成 `null`，而 `null` 在这套接口里的语义是"不设上限"：
 * `max_bytes` 打错一个字 → 体积上限被悄悄取消 → 后端 200 → 界面弹「已保存」。
 * 另一路 `Math.max(1, …)` 会静默把用户按下的 0 改写成 1。
 */
import {describe, expect, it} from 'vitest';
import {parseGcField} from '@/components/SettingsModal';

const KEEP = {field: '保留最近份数', min: 1};
const BYTES = {field: '体积上限（字节）', min: 0};

describe('parseGcField', () => {
	it('显式留空才是"不设上限"', () => {
		expect(parseGcField('', KEEP)).toEqual({ok: true, value: null});
		expect(parseGcField('   ', BYTES)).toEqual({ok: true, value: null});
	});

	it('打错字不再被当成留空 —— 必须拒收并说明原因', () => {
		for (const raw of ['abc', '12ab', '1.2.3', '--5', '1e', 'NaN', 'Infinity']) {
			const r = parseGcField(raw, BYTES);
			expect(r.ok, `写错的 ${raw} 不该被接受`).toBe(false);
			if (!r.ok) expect(r.message).toContain('体积上限');
		}
	});

	it('不静默改写用户输入：低于下限就报错，而不是夹成下限', () => {
		expect(parseGcField('0', KEEP).ok).toBe(false);
		expect(parseGcField('-3', KEEP).ok).toBe(false);
		// 0 对字节上限是合法值（= 不限），不是"太小"
		expect(parseGcField('0', BYTES)).toEqual({ok: true, value: 0});
	});

	it('合法值取整后原样返回', () => {
		expect(parseGcField('5', KEEP)).toEqual({ok: true, value: 5});
		expect(parseGcField(' 7 ', KEEP)).toEqual({ok: true, value: 7});
		expect(parseGcField('4096.9', BYTES)).toEqual({ok: true, value: 4096});
	});
});
