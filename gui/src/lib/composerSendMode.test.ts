import {describe, expect, it} from 'vitest';

import {resolveSendMode, steerHintVisible} from './composerSendMode';

/**
 * 忙时发送方式：Enter=排队（既有语义）、Ctrl/Cmd+Enter=引导（边界投递）。
 * 非忙时两者等价——引导只在"任务正在跑"时有意义。
 */
describe('resolveSendMode', () => {
	it('空闲时一律普通发送（哪怕按了组合键）', () => {
		expect(resolveSendMode({streaming: false, modifier: false, enter: true})).toBe('send');
		expect(resolveSendMode({streaming: false, modifier: true, enter: true})).toBe('send');
	});

	it('忙时裸 Enter 仍是排队（默认行为不变）', () => {
		expect(resolveSendMode({streaming: true, modifier: false, enter: true})).toBe('send');
	});

	it('忙时 Ctrl/Cmd+Enter = 引导', () => {
		expect(resolveSendMode({streaming: true, modifier: true, enter: true})).toBe('steer');
	});

	it('未按 Enter（换行等）不触发发送', () => {
		expect(resolveSendMode({streaming: true, modifier: true, enter: false})).toBe('send');
	});
});

describe('steerHintVisible', () => {
	it('只在忙时提示「可引导」', () => {
		expect(steerHintVisible(true)).toBe(true);
		expect(steerHintVisible(false)).toBe(false);
	});
});
