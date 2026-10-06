import {describe, expect, it} from 'vitest';

import {
	queueCountLabel,
	queueDockView,
	queueImageRefs,
	shouldCollapseQueueDock,
} from './inboxDockPresentation';

describe('queueDockView', () => {
	it('空队列不出计数头，也不列任何行', () => {
		expect(queueDockView({count: 0, collapsed: true, interactionActive: false})).toEqual({
			showHeader: false,
			expanded: false,
			listVisible: false,
		});
	});

	it('单条不配计数头，且永远直接可见（折叠偏好不吃单条）', () => {
		expect(queueDockView({count: 1, collapsed: true, interactionActive: false})).toEqual({
			showHeader: false,
			expanded: false,
			listVisible: true,
		});
	});

	it('多条默认折叠成计数头，列表不渲染', () => {
		expect(queueDockView({count: 3, collapsed: true, interactionActive: false})).toEqual({
			showHeader: true,
			expanded: false,
			listVisible: false,
		});
	});

	it('多条且已展开时列表渲染', () => {
		expect(queueDockView({count: 3, collapsed: false, interactionActive: false})).toEqual(
			{
				showHeader: true,
				expanded: true,
				listVisible: true,
			},
		);
	});

	it('折叠态下有人编辑/动作在飞 ⇒ 强制展开（否则用户看不见自己在改哪行）', () => {
		expect(queueDockView({count: 3, collapsed: true, interactionActive: true})).toEqual({
			showHeader: true,
			expanded: true,
			listVisible: true,
		});
	});
});

describe('shouldCollapseQueueDock', () => {
	it('清空后收回折叠；本来就折叠则不动', () => {
		expect(shouldCollapseQueueDock(0, false)).toBe(true);
		expect(shouldCollapseQueueDock(0, true)).toBe(false);
		expect(shouldCollapseQueueDock(2, false)).toBe(false);
	});
});

describe('queueCountLabel', () => {
	it('计数头中文带条数', () => {
		expect(queueCountLabel(3)).toBe('3 条排队消息');
	});
});

describe('queueImageRefs', () => {
	it('只留解得开的媒体引用，脏值与空值不出缩略图', () => {
		const ref = `xeyo-media://${'a'.repeat(64)}`;
		expect(queueImageRefs([ref, '', '   ', 'file:///tmp/x.png', undefined as never])).toEqual([
			ref,
		]);
		expect(queueImageRefs(undefined)).toEqual([]);
	});
});
