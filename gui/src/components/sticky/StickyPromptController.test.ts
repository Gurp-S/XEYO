import {describe, expect, it, vi} from 'vitest';
import {checkNoGhostEditingBubble} from './stickyContract';
import {StickyPromptController} from './StickyPromptController';

describe('StickyPromptController phase machine', () => {
	it('starts idle and clears to idle', () => {
		const ctrl = new StickyPromptController({
			getMessages: () => [],
		});
		expect(ctrl.getPhase()).toEqual({kind: 'idle'});
		ctrl.resetSession();
		expect(ctrl.getPhase()).toEqual({kind: 'idle'});
		ctrl.dispose();
	});

	it('beginEdit without pin → editing (in-flow)', () => {
		const onHost = vi.fn();
		const ctrl = new StickyPromptController({
			getMessages: () => [],
			onEditPortalHostChange: onHost,
		});
		const result = ctrl.beginEdit({id: 'm1', text: 'hello'});
		expect(result.usedPortal).toBe(false);
		expect(result.portalHost).toBeNull();
		expect(result.placeholderHeight).toBeGreaterThan(0);
		expect(ctrl.getEditPlaceholderHeight()).toBe(result.placeholderHeight);
		expect(ctrl.getPhase()).toEqual({kind: 'editing', id: 'm1'});
		ctrl.endEdit();
		expect(ctrl.getPhase()).toEqual({kind: 'idle'});
		expect(onHost).not.toHaveBeenCalled();
		ctrl.dispose();
	});

	it('beginEdit measures chip height for placeholder (not always 88)', () => {
		const ctrl = new StickyPromptController({
			getMessages: () => [],
		});
		const scroller = document.createElement('div');
		const content = document.createElement('div');
		const overlay = document.createElement('div');
		document.body.append(scroller, content, overlay);
		ctrl.bindDom({scroller, content, overlay});

		const shell = document.createElement('div');
		shell.setAttribute('data-xy-stuck', '1');
		shell.classList.add('xy-prompt-is-stuck');
		const chip = document.createElement('div');
		chip.setAttribute('data-xy-prompt-chip', '');
		Object.defineProperty(chip, 'getBoundingClientRect', {
			value: () => ({
				top: 10,
				left: 20,
				width: 400,
				height: 52,
				bottom: 62,
				right: 420,
				x: 20,
				y: 10,
				toJSON() {},
			}),
		});
		shell.appendChild(chip);
		scroller.appendChild(shell);
		ctrl.registerShell('m2', shell, true);

		const pin = document.createElement('div');
		pin.dataset.pinId = 'm2';
		pin.style.width = '400px';
		pin.style.left = '0px';
		pin.style.top = '10px';
		overlay.appendChild(pin);
		ctrl.getPinDomNodes().set('m2', pin);

		const result = ctrl.beginEdit({id: 'm2', text: 'short'});
		expect(result.usedPortal).toBe(true);
		expect(result.placeholderHeight).toBe(52);
		expect(ctrl.getEditPlaceholderHeight()).toBe(52);
		expect(chip.style.height).toBe('52px');

		ctrl.endEdit();
		ctrl.dispose();
		scroller.remove();
		content.remove();
		overlay.remove();
	});

	it('beginEdit of non-stuck chip builds a portable host (A-route uni-portal)', () => {
		const onHost = vi.fn();
		const ctrl = new StickyPromptController({
			getMessages: () => [],
			onEditPortalHostChange: onHost,
		});
		const scroller = document.createElement('div');
		const content = document.createElement('div');
		const overlay = document.createElement('div');
		document.body.append(scroller, content, overlay);
		ctrl.bindDom({scroller, content, overlay});

		// 未吸顶（上滚后点编辑）：shell/chip 在流内，无既有 pin 宿主
		const shell = document.createElement('div');
		const chip = document.createElement('div');
		chip.setAttribute('data-xy-prompt-chip', '');
		Object.defineProperty(chip, 'getBoundingClientRect', {
			value: () => ({
				top: 10,
				left: 20,
				width: 400,
				height: 52,
				bottom: 62,
				right: 420,
				x: 20,
				y: 10,
				toJSON() {},
			}),
		});
		shell.appendChild(chip);
		scroller.appendChild(shell);
		ctrl.registerShell('m6', shell, true);

		const result = ctrl.beginEdit({id: 'm6', text: 'scrolled away'});
		expect(result.usedPortal).toBe(true);
		expect(result.portalHost).not.toBeNull();
		expect(result.placeholderHeight).toBe(52);

		// 自动补建的宿主已挂到 overlay 并按 chip 视口位置定位
		const host = ctrl.getEditPortalHost();
		expect(host).not.toBeNull();
		expect(onHost).toHaveBeenCalledWith(host);
		expect(host!.isConnected).toBe(true);
		expect(host!.dataset.pinId).toBe('m6');
		expect(host!.style.left).toBe('20px');
		expect(host!.style.top).toBe('10px');
		expect(host!.style.width).toBe('400px');
		expect(ctrl.getPinDomNodes().get('m6')).toBe(host);

		// 非吸顶 portal 编辑整套快照契约合法：C3 强制 stuck、C4 不入 pins、C5 无洞
		expect(ctrl.collect()).not.toBeNull();
		expect(ctrl.verifyContract()).toEqual([]);

		ctrl.endEdit();
		expect(host!.isConnected).toBe(false);
		expect(ctrl.getEditPortalHost()).toBeNull();
		ctrl.dispose();
		scroller.remove();
		content.remove();
		overlay.remove();
	});

	it('editing hole follows visible portal bubble height, not placeholder', () => {
		const ctrl = new StickyPromptController({
			getMessages: () => [],
		});
		const scroller = document.createElement('div');
		const content = document.createElement('div');
		const overlay = document.createElement('div');
		document.body.append(scroller, content, overlay);
		Object.defineProperty(scroller, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 0,
				width: 800,
				height: 600,
				bottom: 600,
				right: 800,
				x: 0,
				y: 0,
				toJSON() {},
			}),
		});
		Object.defineProperty(content, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 0,
				width: 800,
				height: 2000,
				bottom: 2000,
				right: 800,
				x: 0,
				y: 0,
				toJSON() {},
			}),
		});
		Object.defineProperty(content, 'scrollWidth', {value: 800});
		Object.defineProperty(content, 'scrollHeight', {value: 2000});
		ctrl.bindDom({scroller, content, overlay});

		const shell = document.createElement('div');
		shell.setAttribute('data-xy-stuck', '1');
		shell.classList.add('xy-prompt-is-stuck');
		const stickyInner = document.createElement('div');
		stickyInner.className = 'xy-prompt-sticky';
		stickyInner.setAttribute('data-xy-stuck', '1');
		const chip = document.createElement('div');
		chip.setAttribute('data-xy-prompt-chip', '');
		chip.dataset.promptText = 'hello';
		Object.defineProperty(chip, 'getBoundingClientRect', {
			value: () => ({
				top: 10,
				left: 100,
				width: 400,
				height: 52,
				bottom: 62,
				right: 500,
				x: 100,
				y: 10,
				toJSON() {},
			}),
		});
		Object.defineProperty(stickyInner, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 100,
				width: 400,
				height: 52,
				bottom: 52,
				right: 500,
				x: 100,
				y: 0,
				toJSON() {},
			}),
		});
		stickyInner.appendChild(chip);
		shell.appendChild(stickyInner);
		scroller.appendChild(shell);
		ctrl.registerShell('m3', shell, true);

		const pin = document.createElement('div');
		pin.dataset.pinId = 'm3';
		pin.style.width = '400px';
		pin.style.left = '100px';
		pin.style.top = '10px';
		overlay.appendChild(pin);
		ctrl.getPinDomNodes().set('m3', pin);

		ctrl.beginEdit({id: 'm3', text: 'hello'});
		expect(ctrl.getEditPortalHost()).toBe(pin);

		const editingBubble = document.createElement('div');
		editingBubble.className = 'xy-editing-bubble';
		Object.defineProperty(editingBubble, 'getBoundingClientRect', {
			value: () => ({
				top: 10,
				left: 100,
				width: 400,
				height: 140,
				bottom: 150,
				right: 500,
				x: 100,
				y: 10,
				toJSON() {},
			}),
		});
		pin.appendChild(editingBubble);

		const snap = ctrl.collect();
		expect(snap).not.toBeNull();
		/* 阶段1 自绘壁纸（灰度默认开）：不再产生 clip 洞，几何走 editPortal */
		expect(snap!.holes).toHaveLength(0);
		/* pin 布局保持在占位高度 */
		expect(snap!.editPortal?.height).toBe(52);

		ctrl.endEdit();
		ctrl.dispose();
		scroller.remove();
		content.remove();
		overlay.remove();
	});

	it('setEditPlaceholderHeight grows beyond 88 and locks chip', () => {
		const ctrl = new StickyPromptController({
			getMessages: () => [],
		});
		const scroller = document.createElement('div');
		const content = document.createElement('div');
		const overlay = document.createElement('div');
		document.body.append(scroller, content, overlay);
		ctrl.bindDom({scroller, content, overlay});

		const shell = document.createElement('div');
		shell.setAttribute('data-xy-stuck', '1');
		const chip = document.createElement('div');
		chip.setAttribute('data-xy-prompt-chip', '');
		Object.defineProperty(chip, 'getBoundingClientRect', {
			value: () => ({
				top: 10,
				left: 20,
				width: 400,
				height: 52,
				bottom: 62,
				right: 420,
				x: 20,
				y: 10,
				toJSON() {},
			}),
		});
		shell.appendChild(chip);
		scroller.appendChild(shell);
		ctrl.registerShell('m4', shell, true);

		const pin = document.createElement('div');
		pin.dataset.pinId = 'm4';
		pin.style.width = '400px';
		pin.style.left = '0px';
		pin.style.top = '10px';
		overlay.appendChild(pin);
		ctrl.getPinDomNodes().set('m4', pin);

		ctrl.beginEdit({id: 'm4', text: 'grow'});
		expect(ctrl.getEditPlaceholderHeight()).toBe(52);
		expect(ctrl.setEditPlaceholderHeight(140)).toBe(true);
		expect(ctrl.getEditPlaceholderHeight()).toBe(140);
		expect(chip.style.height).toBe('140px');
		expect(ctrl.setEditPlaceholderHeight(140)).toBe(false);

		ctrl.endEdit();
		ctrl.dispose();
		scroller.remove();
		content.remove();
		overlay.remove();
	});

	it('verifyContract passes while editing with portal + visible hole', () => {
		const ctrl = new StickyPromptController({
			getMessages: () => [],
		});
		const scroller = document.createElement('div');
		const content = document.createElement('div');
		const overlay = document.createElement('div');
		document.body.append(scroller, content, overlay);
		Object.defineProperty(scroller, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 0,
				width: 800,
				height: 600,
				bottom: 600,
				right: 800,
				x: 0,
				y: 0,
				toJSON() {},
			}),
		});
		Object.defineProperty(content, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 0,
				width: 800,
				height: 2000,
				bottom: 2000,
				right: 800,
				x: 0,
				y: 0,
				toJSON() {},
			}),
		});
		ctrl.bindDom({scroller, content, overlay});

		const shell = document.createElement('div');
		shell.setAttribute('data-xy-stuck', '1');
		const stickyInner = document.createElement('div');
		stickyInner.className = 'xy-prompt-sticky';
		stickyInner.setAttribute('data-xy-stuck', '1');
		Object.defineProperty(stickyInner, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 100,
				width: 400,
				height: 52,
				bottom: 52,
				right: 500,
				x: 100,
				y: 0,
				toJSON() {},
			}),
		});
		const chip = document.createElement('div');
		chip.setAttribute('data-xy-prompt-chip', '');
		Object.defineProperty(chip, 'getBoundingClientRect', {
			value: () => ({
				top: 0,
				left: 100,
				width: 400,
				height: 52,
				bottom: 52,
				right: 500,
				x: 100,
				y: 0,
				toJSON() {},
			}),
		});
		stickyInner.appendChild(chip);
		shell.appendChild(stickyInner);
		scroller.appendChild(shell);
		ctrl.registerShell('m5', shell, true);

		const pin = document.createElement('div');
		pin.dataset.pinId = 'm5';
		pin.style.width = '400px';
		pin.style.left = '100px';
		pin.style.top = '10px';
		overlay.appendChild(pin);
		ctrl.getPinDomNodes().set('m5', pin);

		const begin = ctrl.beginEdit({id: 'm5', text: 'contract'});
		expect(begin.usedPortal).toBe(true);
		expect(begin.placeholderHeight).toBe(52);

		const editingBubble = document.createElement('div');
		editingBubble.className = 'xy-editing-bubble';
		Object.defineProperty(editingBubble, 'getBoundingClientRect', {
			value: () => ({
				top: 10,
				left: 100,
				width: 400,
				height: 140,
				bottom: 150,
				right: 500,
				x: 100,
				y: 10,
				toJSON() {},
			}),
		});
		pin.appendChild(editingBubble);

		expect(ctrl.verifyContract()).toEqual([]);
		expect(checkNoGhostEditingBubble(shell, true)).toEqual([]);

		ctrl.endEdit();
		expect(pin.isConnected).toBe(false);
		ctrl.dispose();
		scroller.remove();
		content.remove();
		overlay.remove();
	});
});
