/**
 * composerSendMode —— 忙时发送方式决策（纯函数，便于单测）。
 *
 * 语义取自 DSH 的 `ComposerSubmissionPolicy.resolve`
 * （packages/client/ui-conversation/src/client/input/submission-policy.ts:44）：
 * 忙时裸 Enter 走用户偏好，Ctrl/Cmd+Enter 走偏好的**反面**；
 * 不可引导的会话（侧会话 / 子 agent / 没在跑）两个键都落回排队发送。
 * 偏好默认 `queue`，与 XEYO 既有行为逐字相同。
 *
 * 放在独立模块而不是 Composer 里：Composer 是巨石，只留接线点；
 * 判定本身可单测（见 composerSendMode.test.ts）。
 */

export type SendMode = 'send' | 'steer';

/** 忙时裸 Enter 的含义（与 DSH 的 `busyEnter` 字段同名同值域）。 */
export type BusyEnterBehavior = 'queue' | 'steer';

export const BUSY_ENTER_BEHAVIORS = ['queue', 'steer'] as const;

/** 默认档：忙时裸 Enter 排队（= XEYO 既有行为，不改默认）。 */
export const DEFAULT_BUSY_ENTER: BusyEnterBehavior = 'queue';

/** 读路径收口：设置里的脏值/缺值一律落回默认档，绝不抛。 */
export function normalizeBusyEnter(value: unknown): BusyEnterBehavior {
	return value === 'steer' ? 'steer' : DEFAULT_BUSY_ENTER;
}

export type SendModeInput = {
	/** 当前会话是否正在生成（streaming）。 */
	streaming: boolean;
	/** 组合键：Ctrl（Windows/Linux）或 Cmd（macOS）。 */
	modifier: boolean;
	/** 触发键是 Enter（Shift+Enter 换行不在此列）。 */
	enter: boolean;
	/** 本次会话是否支持引导；显式传 false 时两个键都只排队。 */
	steeringAvailable?: boolean;
	/** 用户偏好：忙时裸 Enter 走排队还是引导。缺省 = 默认档。 */
	busyEnter?: BusyEnterBehavior;
};

/** 解析本次发送应走哪条路：普通发送（排队） / 引导（忙时的边界投递）。 */
export function resolveSendMode(input: SendModeInput): SendMode {
	if (!input.enter || !input.streaming || input.steeringAvailable === false) {
		return 'send';
	}
	const preferred = input.busyEnter ?? DEFAULT_BUSY_ENTER;
	// 加速键恒为偏好的反面：DSH 的两个键是一对可翻转的组合，不是硬编码的
	// 「裸 Enter 排队 + 加速键引导」。
	const wantsSteer = input.modifier
		? preferred === 'queue'
		: preferred === 'steer';
	return wantsSteer ? 'steer' : 'send';
}

/** 忙时是否该在输入区提示「可引导」。 */
export function steerHintVisible(streaming: boolean): boolean {
	return streaming;
}

/**
 * 忙时状态条上的键位说明。措辞必须由偏好决定——否则提示会说谎：
 * 偏好翻成「引导」后，裸 Enter 才是引导，加速键反而是排队。
 */
export function busyChordHint(busyEnter: BusyEnterBehavior): string {
	return busyEnter === 'steer'
		? 'Enter 引导本回合 · Ctrl+Enter 排队'
		: 'Ctrl+Enter 引导本回合 · Enter 排队';
}

/** 空闲态的输入行提示（DSH 的默认 placeholder 同位）。 */
export const IDLE_PLACEHOLDER = '描述任务… / 指令 @ 文件';

/**
 * 输入行 placeholder（DSH 口径：键位提示写在输入行里，卡外不留第二行）。
 * 忙且草稿为空时提示占位；一开始打字就退回默认文案——那时提示已由
 * 主键形状（发送↔停止）与快捷键本身承担。
 */
export function composerPlaceholder(input: {
	busy: boolean;
	hasDraft: boolean;
	busyEnter: BusyEnterBehavior;
}): string {
	if (!input.busy || input.hasDraft) {
		return IDLE_PLACEHOLDER;
	}
	return busyChordHint(input.busyEnter);
}
