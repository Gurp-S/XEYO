import {describe, expect, it} from 'vitest';
import {anchoredMenuGeometry} from './anchoredMenuGeometry';

describe('anchored menus stay reachable', () => {
	it('clamps a wide model menu whose trigger is left of the viewport center', () => {
		const p = anchoredMenuGeometry({top: 408, bottom: 436, right: 391}, {width: 720, height: 480}, 508);
		expect(720 - p.right - 508).toBe(8);
		expect(p.placement).toBe('above');
		expect(480 - p.bottom! - p.maxHeight).toBe(8);
	});
	it('opens below a history editor near the top, with room for the bottom gutter', () => {
		const p = anchoredMenuGeometry({top: 28, bottom: 56, right: 700}, {width: 720, height: 480}, 508);
		expect(p.placement).toBe('below');
		expect(p.top).toBe(64);
		expect(p.top! + p.maxHeight).toBe(472);
	});
	it('retains right alignment when both menu edges fit', () => {
		const p = anchoredMenuGeometry({top: 700, bottom: 728, right: 900}, {width: 1280, height: 800}, 508);
		expect(p.right).toBe(380);
	});
	it('caps the width used for positioning when zoom makes the menu wider than the viewport', () => {
		const p = anchoredMenuGeometry({top: 400, bottom: 430, right: 260}, {width: 720, height: 480}, 1016);
		expect(p.right).toBe(8);
	});
});
