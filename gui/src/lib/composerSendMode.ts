/**
 * composerSendMode —— 忙时发送方式决策（纯函数，便于单测）。
 *
 * 语义（对齐 Codex 的「引导」）：
 * - `Enter`：**排队**（等本轮 settle 后投递；既有语义不变）
 * - `Ctrl/Cmd+Enter`：**引导**（本轮下一个边界就投给模型，不打断工具批次）
 * - 非忙时：两者等价（都只是普通发送）
 *
 * 放在独立模块而不是 Composer 里：Composer 是巨石，只留接线点；
 * 判定本身可单测（见 composerSendMode.test.ts）。
 */

export type SendMode = 'send' | 'steer';

export type SendModeInput = {
	/** 当前会话是否正在生成（streaming）。 */
	streaming: boolean;
	/** 组合键：Ctrl（Windows/Linux）或 Cmd（macOS）。 */
	modifier: boolean;
	/** 触发键是 Enter（Shift+Enter 换行不在此列）。 */
	enter: boolean;
};

/** 解析本次发送应走哪条路：普通发送 / 引导（忙时的边界投递）。 */
export function resolveSendMode(input: SendModeInput): SendMode {
	if (input.enter && input.streaming && input.modifier) {
		return 'steer';
	}
	return 'send';
}

/** 忙时是否该在输入区提示「可 Ctrl+Enter 引导」。 */
export function steerHintVisible(streaming: boolean): boolean {
	return streaming;
}
