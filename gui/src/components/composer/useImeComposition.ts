/**
 * IME 组词期间的文本渲染所有权时序。
 *
 * 结构性根因:浏览器把 `compositionend` 排在「携带提交后文本的 change 事件」
 * 之前。Composer 的自绘光标方案里,「谁渲染文本」是二选一的(textarea 自己渲染
 * = 组词期 / 镜像覆盖层渲染 = 平时)。如果在 compositionend 当场把所有权交回
 * 覆盖层,那一次 commit 用的还是"提交前的 value":textarea 已经被设成透明不再
 * 显示自己的文本,而镜像画的又是旧文本 —— 那一帧整行文本对不上,用户看到的就是
 * 一闪(中文每上屏一个词一次)。
 *
 * 修法:compositionend 只挂起"待交还"标记,真正的交还推迟到下一次 value 提交
 * (change)的那一次 commit,让「新文本」与「渲染者切换」落在同一帧,中间不存在
 * 任何"两边都不是新文本"的帧。
 *
 * 两侧边界:
 * - 组词期间的 change 事件(候选更新)不触发交还 —— 那时还没有提交语义;
 * - 引擎在取消组词(如 Esc)后可能不发 change,此时由外部事件收口(失焦/提交:
 *   DOM 值与 value 已一致,交还安全),不做定时兜底 —— 定时器只会在正常引擎上
 *   提前交还,把要修的帧重新造出来。
 */

import {useCallback, useRef, useState} from 'react';

export interface ImeCompositionController {
	/** true = 由 textarea 自己渲染文本(组词期 / 已提交待交还)。 */
	imeRendering: boolean;
	onCompositionStart: () => void;
	onCompositionEnd: () => void;
	/** textarea 每次 change(value 提交)后调用。 */
	onValueCommit: () => void;
	/** 外部收口点(失焦/发送等):放弃待交还标记,立即交还。 */
	onSettle: () => void;
}

export function useImeComposition(): ImeCompositionController {
	const [imeRendering, setImeRendering] = useState(false);
	/** 已 compositionend、等下一次 value 提交再交还。 */
	const pendingRef = useRef(false);

	const onCompositionStart = useCallback(() => {
		pendingRef.current = false;
		setImeRendering(true);
	}, []);

	const onCompositionEnd = useCallback(() => {
		/* 只挂起:保持 imeRendering=true,textarea 继续渲染自己的文本 */
		pendingRef.current = true;
	}, []);

	const onValueCommit = useCallback(() => {
		if (!pendingRef.current) {
			return;
		}
		pendingRef.current = false;
		setImeRendering(false);
	}, []);

	const onSettle = useCallback(() => {
		pendingRef.current = false;
		setImeRendering(false);
	}, []);

	return {
		imeRendering,
		onCompositionStart,
		onCompositionEnd,
		onValueCommit,
		onSettle,
	};
}
