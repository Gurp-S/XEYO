import {describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {vendorReasoningLevels} from './settingsStore';

describe('vendorReasoningLevels — 厂商 modes 预填思考等级', () => {
	it('按全局展示顺序返回声明过的等级', () => {
		expect(
			vendorReasoningLevels({
				modes: {
					reasoning_effort: [{id: 'max'}, {id: 'low'}, {id: 'high'}],
				},
			}),
		).toEqual(['low', 'high', 'max']);
	});

	it('接受字符串形式（兼容网关常见形态）', () => {
		expect(
			vendorReasoningLevels({modes: {reasoning_effort: ['high', 'low']}}),
		).toEqual(['low', 'high']);
	});

	it('剔除非法值与重复值', () => {
		expect(
			vendorReasoningLevels({
				modes: {
					reasoning_effort: [
						{id: 'high'},
						{id: 'high'},
						{id: 'bogus'},
						{id: ''},
						null,
						42,
					],
				},
			}),
		).toEqual(['high']);
	});

	it('未声明 reasoning_effort → 空数组（语义为不限）', () => {
		expect(vendorReasoningLevels({})).toEqual([]);
		expect(vendorReasoningLevels({modes: {}})).toEqual([]);
		expect(vendorReasoningLevels({modes: {reasoning_effort: undefined}})).toEqual(
			[],
		);
	});

	it('非数组形态（畸形响应）不抛错，返回空数组', () => {
		expect(vendorReasoningLevels({modes: {reasoning_effort: 'high'}})).toEqual(
			[],
		);
		expect(vendorReasoningLevels({modes: {reasoning_effort: {id: 'high'}}})).toEqual(
			[],
		);
	});

	it('全部八档都能识别', () => {
		expect(
			vendorReasoningLevels({
				modes: {
					reasoning_effort: [
						'ultra',
						'max',
						'xhigh',
						'high',
						'medium',
						'low',
						'minimal',
						'none',
					],
				},
			}),
		).toEqual([
			'none',
			'minimal',
			'low',
			'medium',
			'high',
			'xhigh',
			'max',
			'ultra',
		]);
	});
});
