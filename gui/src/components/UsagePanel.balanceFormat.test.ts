/**
 * UsagePanel 的余额格式化 —— "厂商没给数" 与 "余额是 0" 必须是两种显示。
 *
 * 旧实现有两个问题（都是实测，不是假设）：
 * - `!Number.isFinite(n)` 分支和函数末尾返回值**逐字相同**，是个死判断；
 * - 于是 `fmtBalance('')` 输出一个光秃的 `¥`、`fmtBalance('abc')` 输出 `¥abc` ——
 *   把"没查到"画成了一个具体的金额符号，与后端 money 口径（缺失用量记「费用未知」，
 *   永不按 0 计入）相悖。
 */
import {describe, expect, it} from 'vitest';
import {fmtBalance} from '@/components/UsagePanel';

describe('fmtBalance', () => {
	it('真实的 0 仍然显示为 0，不被当成缺失', () => {
		expect(fmtBalance('0')).toBe('¥0');
		expect(fmtBalance('0.00')).toBe('¥0.00');
	});

	it('缺字段 / 空串 / 纯空白 / 非数字一律是「未知」而不是光秃的符号', () => {
		expect(fmtBalance('')).toBe('—');
		expect(fmtBalance('   ')).toBe('—');
		expect(fmtBalance('abc')).toBe('—');
		expect(fmtBalance(undefined as unknown as string)).toBe('—');
		expect(fmtBalance(null as unknown as string)).toBe('—');
		expect(fmtBalance('Infinity')).toBe('—');
	});

	it('币种按厂商给的走，没给才落人民币', () => {
		expect(fmtBalance('12.34', 'USD')).toBe('$12.34');
		expect(fmtBalance('12.34', 'usd')).toBe('$12.34');
		expect(fmtBalance('12.34', 'CNY')).toBe('¥12.34');
		expect(fmtBalance('12.34')).toBe('¥12.34');
	});

	it('不会给未知值配上货币符号', () => {
		for (const raw of ['', ' ', 'N/A', '--']) {
			expect(fmtBalance(raw, 'USD')).not.toMatch(/[$¥]/);
		}
	});
});
