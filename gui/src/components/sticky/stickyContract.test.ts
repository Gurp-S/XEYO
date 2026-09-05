import {describe, expect, it} from 'vitest';
import {
	STICKY_CONTRACT_RULES,
	STICKY_CONTRACT_VERSION,
	checkBeginEditContract,
	checkEditingSnapContract,
	checkEndEditContract,
	checkNoGhostEditingBubble,
} from './stickyContract';
import {PROMPT_CHIP_VIEW_MAX_PX, type StuckSnap} from './stickyTypes';

describe('stickyContract freeze', () => {
	it('keeps version and rule ids stable', () => {
		expect(STICKY_CONTRACT_VERSION).toBe(4);
		expect(STICKY_CONTRACT_RULES.map(r => r.id)).toEqual([
			'C1',
			'C2',
			'C3',
			'C4',
			'C5',
			'C6',
			'C7',
		]);
	});

	it('C1: stuck beginEdit must use portal', () => {
		expect(
			checkBeginEditContract({
				stuck: true,
				usedPortal: false,
				portalHost: null,
				placeholderHeight: 52,
				measuredChipHeight: 52,
			}),
		).toEqual([
			expect.objectContaining({rule: 'C1'}),
		]);
		const host = document.createElement('div');
		expect(
			checkBeginEditContract({
				stuck: true,
				usedPortal: true,
				portalHost: host,
				placeholderHeight: 52,
				measuredChipHeight: 52,
			}),
		).toEqual([]);
	});

	it('C2: portal placeholder ≤ view max and matches measure; in-place free', () => {
		const host = document.createElement('div');
		/* portal 路径：超统一查看上限 → 违例 */
		expect(
			checkBeginEditContract({
				stuck: false,
				usedPortal: true,
				portalHost: host,
				placeholderHeight: PROMPT_CHIP_VIEW_MAX_PX + 1,
				measuredChipHeight: PROMPT_CHIP_VIEW_MAX_PX + 1,
			}).some(v => v.rule === 'C2'),
		).toBe(true);
		/* portal 路径：≤ 上限且与测量一致 → 通过 */
		expect(
			checkBeginEditContract({
				stuck: false,
				usedPortal: true,
				portalHost: host,
				placeholderHeight: 52,
				measuredChipHeight: 52,
			}),
		).toEqual([]);
		/* portal 路径：测量超上限时占位钳到上限即可 */
		expect(
			checkBeginEditContract({
				stuck: true,
				usedPortal: true,
				portalHost: host,
				placeholderHeight: PROMPT_CHIP_VIEW_MAX_PX,
				measuredChipHeight: 5000,
			}),
		).toEqual([]);
		/* 就地编辑：占位 = 芯片实高，可超上限（有限正值即可） */
		expect(
			checkBeginEditContract({
				stuck: false,
				usedPortal: false,
				portalHost: null,
				placeholderHeight: 5000,
				measuredChipHeight: 5000,
			}),
		).toEqual([]);
	});

	it('C3–C5: editing snap forces stuck, portal, holes forbidden', () => {
		const snap: StuckSnap = {
			pins: [{id: 'other', text: '', left: 0, top: 0, width: 10, height: 10}],
			holes: [],
			editPortal: {
				id: 'm1',
				text: 'hi',
				left: 0,
				top: 10,
				width: 400,
				height: 52,
			},
			contentW: 800,
			contentH: 2000,
			nodes: [
				{
					id: 'm1',
					node: document.createElement('div'),
					stuck: true,
					chip: document.createElement('div'),
				},
			],
		};
		expect(
			checkEditingSnapContract({
				editingId: 'm1',
				snap,
				visibleEditHeight: 140,
				visibleEditWidth: 400,
			}),
		).toEqual([]);

		const unstuck = {
			...snap,
			nodes: [{...snap.nodes[0]!, stuck: false}],
		};
		expect(
			checkEditingSnapContract({
				editingId: 'm1',
				snap: unstuck,
				visibleEditHeight: 140,
				visibleEditWidth: 400,
			}).some(v => v.rule === 'C3'),
		).toBe(true);

		const inPins = {
			...snap,
			pins: [...snap.pins, snap.editPortal!],
			editPortal: null,
		};
		expect(
			checkEditingSnapContract({
				editingId: 'm1',
				snap: inPins,
				visibleEditHeight: null,
				visibleEditWidth: null,
			}).some(v => v.rule === 'C4'),
		).toBe(true);

		/* 就地编辑（smoke-test #10）：无 portal、未吸顶、不在 pins → 通过 */
		const inFlowClean: StuckSnap = {
			...snap,
			pins: [],
			holes: [],
			editPortal: null,
			nodes: [{...snap.nodes[0]!, stuck: false}],
		};
		expect(
			checkEditingSnapContract({
				editingId: 'm1',
				snap: inFlowClean,
				visibleEditHeight: null,
				visibleEditWidth: null,
			}),
		).toEqual([]);
		/* 就地编辑却处于吸附（C3 反向：禁止把流内编辑拽到吸顶）→ 违例 */
		expect(
			checkEditingSnapContract({
				editingId: 'm1',
				snap: {...inFlowClean, nodes: [{...snap.nodes[0]!, stuck: true}]},
				visibleEditHeight: null,
				visibleEditWidth: null,
			}).some(v => v.rule === 'C3'),
		).toBe(true);

		/* C5（自绘壁纸，默认）：残留 clip 洞 → 违例 */
		const withHoles = {
			...snap,
			holes: [{x: 0, y: 10, w: 400, h: 140, r: 16}],
		};
		expect(
			checkEditingSnapContract({
				editingId: 'm1',
				snap: withHoles,
				visibleEditHeight: null,
				visibleEditWidth: null,
			}).some(v => v.rule === 'C5'),
		).toBe(true);

		/* C5（legacy 挖孔路径）：洞盖住可视气泡 → 通过 */
		expect(
			checkEditingSnapContract(
				{
					editingId: 'm1',
					snap: withHoles,
					visibleEditHeight: 140,
					visibleEditWidth: 400,
				},
				{legacyHoles: true},
			),
		).toEqual([]);
		/* C5（legacy 挖孔路径）：洞不跟可视气泡 → 违例 */
		expect(
			checkEditingSnapContract(
				{
					editingId: 'm1',
					snap: withHoles,
					visibleEditHeight: 200,
					visibleEditWidth: 400,
				},
				{legacyHoles: true},
			).some(v => v.rule === 'C5'),
		).toBe(true);
	});

	it('C6: endEdit must clear host', () => {
		const host = document.createElement('div');
		document.body.appendChild(host);
		expect(
			checkEndEditContract({
				editingId: null,
				portalHost: null,
				previousHost: host,
			}).some(v => v.rule === 'C6'),
		).toBe(true);
		host.remove();
		expect(
			checkEndEditContract({
				editingId: null,
				portalHost: null,
				previousHost: host,
			}),
		).toEqual([]);
	});

	it('C7: no in-flow editing bubble on portal path', () => {
		const shell = document.createElement('div');
		const bubble = document.createElement('div');
		bubble.className = 'xy-editing-bubble';
		shell.appendChild(bubble);
		expect(
			checkNoGhostEditingBubble(shell, true).some(v => v.rule === 'C7'),
		).toBe(true);
		bubble.remove();
		expect(checkNoGhostEditingBubble(shell, true)).toEqual([]);
		expect(checkNoGhostEditingBubble(shell, false)).toEqual([]);
	});
});
