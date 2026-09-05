/**
 * Sticky 编辑契约（冻结版）。
 *
 * 变更须同步：本文件 VERSION、规则表、纯检查函数、StickyPromptController 调用点、
 * stickyContract.test.ts。禁止在 MessageList 里另起一套占位/洞/portal 规则。
 *
 * C1  stuck 进编辑必须走 portal（禁止流内长高编辑框）
 * C2  占位高度界线：portal 路径流内占位 ≤ 统一查看上限 promptChipMaxPx（且测量值
 *     ≤ 上限时须与芯片实高一致）；就地编辑占位 = 芯片实高（可超上限，有限正值即可）
 * C3  编辑中 stuck 跟随编辑形态：portal 编辑（进编辑时已吸顶）强制 stuck，
 *     就地编辑（未吸顶）禁止吸附 —— 修复"编辑非吸顶消息被拽到顶部不复位"
 *     （smoke-test #10）。就地编辑滚动到吸顶区后转 portal 编辑，同样受本规则约束。
 * C4  编辑中 UI 只在 editPortal（portal 编辑）；就地编辑不得混入 pins
 * C5  自绘壁纸（灰度开，默认）：snap.holes 必须为空（禁止残留 clip-path 挖孔）；
 *     灰度关（legacyHoles）时洞的 w/h 须盖住可见编辑气泡（可含 STICKY_HOLE_PAD）
 * C6  endEdit 必须卸掉 portal host（禁止残留宿主）
 * C7  portal 路径下流内不得再有 .xy-editing-bubble
 */
import {
	STICKY_HOLE_PAD_PX,
	promptChipMaxPx,
	type StuckSnap,
} from './stickyTypes';

export const STICKY_CONTRACT_VERSION = 4 as const;

export type StickyContractRuleId =
	| 'C1'
	| 'C2'
	| 'C3'
	| 'C4'
	| 'C5'
	| 'C6'
	| 'C7';

export type StickyContractRule = {
	id: StickyContractRuleId;
	summary: string;
};

export const STICKY_CONTRACT_RULES: readonly StickyContractRule[] = [
	{id: 'C1', summary: 'stuck beginEdit must use portal host'},
	{
		id: 'C2',
		summary:
			'portal placeholder ≤ unified view max (matches measured when ≤ max); in-place placeholder = measured',
	},
	{id: 'C3', summary: 'editing stuck follows edit form: portal edit stays stuck, in-flow edit must not stick'},
	{id: 'C4', summary: 'editing UI lives on editPortal, never pins'},
	{
		id: 'C5',
		summary:
			'no clip holes when self-wallpaper on; legacy holes track visible edit bubble',
	},
	{id: 'C6', summary: 'endEdit removes portal host from DOM'},
	{
		id: 'C7',
		summary: 'no in-flow .xy-editing-bubble when portal path is active',
	},
] as const;

export type StickyContractViolation = {
	rule: StickyContractRuleId;
	message: string;
	detail?: Record<string, unknown>;
};

const HOLE_TOL_PX = 2;

function violate(
	rule: StickyContractRuleId,
	message: string,
	detail?: Record<string, unknown>,
): StickyContractViolation {
	return detail ? {rule, message, detail} : {rule, message};
}

/** beginEdit 结果：C1 + C2 */
export function checkBeginEditContract(input: {
	stuck: boolean;
	usedPortal: boolean;
	portalHost: HTMLElement | null;
	placeholderHeight: number;
	measuredChipHeight: number;
}): StickyContractViolation[] {
	const out: StickyContractViolation[] = [];
	const {
		stuck,
		usedPortal,
		portalHost,
		placeholderHeight,
		measuredChipHeight,
	} = input;

	if (stuck && (!usedPortal || !portalHost)) {
		out.push(
			violate('C1', 'stuck beginEdit must attach a portal host', {
				stuck,
				usedPortal,
				hasHost: Boolean(portalHost),
			}),
		);
	}

	const chipMax = promptChipMaxPx();
	const finitePositive =
		Number.isFinite(placeholderHeight) && placeholderHeight > 0;
	if (usedPortal) {
		/* portal 路径：流内占位是预留空间，必须 ≤ 统一查看上限；
		   可视测量 ≤ 上限时占位须与芯片实高一致（禁止无谓改高） */
		if (!(finitePositive && placeholderHeight <= chipMax)) {
			out.push(
				violate(
					'C2',
					`portal placeholderHeight must be in (0, ${chipMax}]`,
					{placeholderHeight, chipMax},
				),
			);
		} else if (
			measuredChipHeight > 0 &&
			measuredChipHeight <= chipMax &&
			Math.round(placeholderHeight) !== Math.round(measuredChipHeight)
		) {
			out.push(
				violate(
					'C2',
					'placeholderHeight must match measured chip height when ≤ max',
					{placeholderHeight, measuredChipHeight},
				),
			);
		}
	} else if (!finitePositive) {
		/* 就地编辑：占位 = 进编辑前芯片实高，可超上限（随内容长高） */
		out.push(
			violate(
				'C2',
				'in-place placeholderHeight must be a positive finite number',
				{placeholderHeight},
			),
		);
	}

	return out;
}

/** collect() 编辑中快照：C3 + C4 + C5 */
export function checkEditingSnapContract(
	input: {
		editingId: string;
		snap: StuckSnap;
		visibleEditHeight: number | null;
		visibleEditWidth: number | null;
	},
	opts?: {legacyHoles?: boolean},
): StickyContractViolation[] {
	const out: StickyContractViolation[] = [];
	const {editingId, snap, visibleEditHeight, visibleEditWidth} = input;

	const node = snap.nodes.find(n => n.id === editingId);
	const portalMode = Boolean(snap.editPortal);
	if (portalMode) {
		/* portal 编辑（进编辑时已吸顶 / 就地编辑已滚入吸顶区转 portal）：
		   C3 保持 stuck；C4 编辑气泡只准在 editPortal（且只属 editingId）。 */
		if (snap.editPortal!.id !== editingId) {
			out.push(
				violate('C4', 'editPortal must belong to editingId', {
					editingId,
					editPortalId: snap.editPortal!.id,
				}),
			);
		}
		if (!node?.stuck) {
			out.push(
				violate('C3', 'editing shell must remain stuck in portal mode', {
					editingId,
					found: Boolean(node),
					stuck: node?.stuck ?? false,
				}),
			);
		}
	} else {
		/* 就地编辑（smoke-test #10）：未走 portal 的编辑禁止吸附 ——
		   强制 stuck 会把流内消息拽到吸顶 pin（"气泡不复位"）。 */
		if (node?.stuck) {
			out.push(
				violate('C3', 'in-flow editing shell must not be stuck', {
					editingId,
					found: Boolean(node),
					stuck: node?.stuck ?? false,
				}),
			);
		}
	}
	if (snap.pins.some(p => p.id === editingId)) {
		out.push(
			violate('C4', 'editingId must not appear in pins', {editingId}),
		);
	}

	if (opts?.legacyHoles) {
		if (
			visibleEditHeight != null &&
			visibleEditWidth != null &&
			snap.holes.length > 0
		) {
			/* 洞可含 STICKY_HOLE_PAD；须至少盖住可视气泡，且勿明显过大。 */
			const maxExtra = STICKY_HOLE_PAD_PX * 2 + HOLE_TOL_PX;
			const matched = snap.holes.some(
				h =>
					h.h >= visibleEditHeight - HOLE_TOL_PX &&
					h.w >= visibleEditWidth - HOLE_TOL_PX &&
					h.h <= visibleEditHeight + maxExtra &&
					h.w <= visibleEditWidth + maxExtra,
			);
			if (!matched) {
				out.push(
					violate(
						'C5',
						'clip hole w/h must track visible edit bubble',
						{
							holes: snap.holes.map(h => ({w: h.w, h: h.h})),
							visibleEditWidth,
							visibleEditHeight,
							pad: STICKY_HOLE_PAD_PX,
						},
					),
				);
			}
		}
	} else if (snap.holes.length > 0) {
		/* 自绘壁纸路径（灰度开，默认）：pin/编辑气泡背景自带壁纸，clip 洞必须为空 */
		out.push(
			violate('C5', 'clip holes must not exist when self-wallpaper is on', {
				holes: snap.holes.map(h => ({w: h.w, h: h.h})),
			}),
		);
	}

	return out;
}

/** endEdit 后：C6 */
export function checkEndEditContract(input: {
	editingId: string | null;
	portalHost: HTMLElement | null;
	previousHost: HTMLElement | null;
}): StickyContractViolation[] {
	const out: StickyContractViolation[] = [];
	const {editingId, portalHost, previousHost} = input;

	if (editingId != null) {
		out.push(
			violate('C6', 'editingId must be cleared after endEdit', {
				editingId,
			}),
		);
	}
	if (portalHost != null) {
		out.push(
			violate('C6', 'portalHost ref must be null after endEdit', {}),
		);
	}
	if (previousHost?.isConnected) {
		out.push(
			violate('C6', 'previous portal host must be removed from DOM', {}),
		);
	}

	return out;
}

/** MessageList / 诊断：C7 */
export function checkNoGhostEditingBubble(
	shell: ParentNode | null | undefined,
	usingPortal: boolean,
): StickyContractViolation[] {
	if (!usingPortal || !shell) {
		return [];
	}
	const ghost = shell.querySelector?.('.xy-editing-bubble');
	if (ghost) {
		return [
			violate(
				'C7',
				'in-flow .xy-editing-bubble must not exist on portal path',
			),
		];
	}
	return [];
}

export function reportStickyContract(
	violations: StickyContractViolation[],
	opts?: {throwOnViolation?: boolean},
): void {
	if (violations.length === 0) {
		return;
	}
	const lines = violations.map(
		v =>
			`[sticky-contract ${STICKY_CONTRACT_VERSION}/${v.rule}] ${v.message}`,
	);
	const msg = lines.join('\n');
	if (opts?.throwOnViolation) {
		throw new Error(msg);
	}
	console.warn(msg, violations);
}
