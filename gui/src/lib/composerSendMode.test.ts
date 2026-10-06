import {describe, expect, it} from 'vitest';

import {
	busyChordHint,
	composerPlaceholder,
	IDLE_PLACEHOLDER,
	normalizeBusyEnter,
	resolveSendMode,
	steerHintVisible,
} from './composerSendMode';

/**
 * 忙时发送方式（对齐 DSH 的 submission-policy）：
 * 裸 Enter = 偏好档，Ctrl/Cmd+Enter = 偏好的反面；默认档 queue 即既有行为。
 * 非忙时或不可引导的会话，两个键都只是排队发送。
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

	it('偏好翻成 steer 后两键取反（DSH 的加速键=偏好反面）', () => {
		expect(
			resolveSendMode({streaming: true, modifier: false, enter: true, busyEnter: 'steer'}),
		).toBe('steer');
		expect(
			resolveSendMode({streaming: true, modifier: true, enter: true, busyEnter: 'steer'}),
		).toBe('send');
	});

	it('不可引导的会话两个键都只排队（偏好不得造出引导）', () => {
		expect(
			resolveSendMode({
				streaming: true,
				modifier: false,
				enter: true,
				busyEnter: 'steer',
				steeringAvailable: false,
			}),
		).toBe('send');
		expect(
			resolveSendMode({
				streaming: true,
				modifier: true,
				enter: true,
				busyEnter: 'steer',
				steeringAvailable: false,
			}),
		).toBe('send');
	});
});

describe('normalizeBusyEnter', () => {
	it('只认 steer，其余一律落回默认档', () => {
		expect(normalizeBusyEnter('steer')).toBe('steer');
		expect(normalizeBusyEnter('queue')).toBe('queue');
		expect(normalizeBusyEnter(undefined)).toBe('queue');
		expect(normalizeBusyEnter('引导')).toBe('queue');
	});
});

describe('busyChordHint', () => {
	it('措辞跟随偏好，且两个键各说各的', () => {
		expect(busyChordHint('queue')).toBe('Ctrl+Enter 引导本回合 · Enter 排队');
		expect(busyChordHint('steer')).toBe('Enter 引导本回合 · Ctrl+Enter 排队');
	});
});

describe('composerPlaceholder', () => {
	it('空闲 / 已有草稿 → 默认文案（DSH：提示只在空草稿时占位）', () => {
		expect(
			composerPlaceholder({busy: false, hasDraft: false, busyEnter: 'queue'}),
		).toBe(IDLE_PLACEHOLDER);
		expect(
			composerPlaceholder({busy: true, hasDraft: true, busyEnter: 'queue'}),
		).toBe(IDLE_PLACEHOLDER);
	});

	it('忙且空草稿 → 键位提示进 placeholder，措辞仍随偏好', () => {
		expect(
			composerPlaceholder({busy: true, hasDraft: false, busyEnter: 'queue'}),
		).toBe('Ctrl+Enter 引导本回合 · Enter 排队');
		expect(
			composerPlaceholder({busy: true, hasDraft: false, busyEnter: 'steer'}),
		).toBe('Enter 引导本回合 · Ctrl+Enter 排队');
	});
});


describe('steerHintVisible', () => {
	it('只在忙时提示「可引导」', () => {
		expect(steerHintVisible(true)).toBe(true);
		expect(steerHintVisible(false)).toBe(false);
	});
});
