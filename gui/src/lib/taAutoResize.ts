/**
 * textarea 自动高度:rAF 批处理 + 写保护(2026-09-08 打字跟手优化)。
 *
 * 背景:Composer 每次 commit 后同步 `height=auto → 读 scrollHeight → 写 px`。
 * 这条链在输入事件关键路径上强制同步回流;且高度未变时也写 style.height,
 * 造成每键无谓的样式失效。
 *
 * 这里把「测高 + 写入」整体推迟到下一个动画帧:
 * - 同帧多次 commit(快速连打 / IME 候选上屏 / 程序化 setValue)只测一次;
 * - 高度与 capped 边沿都未变化时不写 style;
 * - 展开态(isExpanded)完全不干预,由调用方接管(保持既有展开/收起语义)。
 *
 * 消费方:Composer.tsx(resizeTa 接线点)。行为契约见 taAutoResize.test.ts。
 */
export interface TaAutoResize {
	/** 调度一次测量+落盘(帧内幂等)。 */
	schedule: (el: HTMLTextAreaElement) => void;
	/** 取消未落盘的帧回调(卸载时调用)。 */
	cancel: () => void;
}

export function createTaAutoResize(opts: {
	minPx: number;
	maxPx: number;
	/** true = 用户手动展开,自动高度退位。 */
	isExpanded: () => boolean;
	/** capped(内容超过 maxPx、出现内部滚动)边沿通知。 */
	onCapped?: (capped: boolean) => void;
}): TaAutoResize {
	let raf = 0;
	let prevCapped: boolean | null = null;

	const run = (el: HTMLTextAreaElement) => {
		raf = 0;
		if (opts.isExpanded()) {
			return;
		}
		// 唯一强制回流点:每帧至多一次
		el.style.height = 'auto';
		const measured = el.scrollHeight;
		const next = Math.min(opts.maxPx, Math.max(opts.minPx, measured));
		const capped = measured >= opts.maxPx;
		const cappedEdge = capped !== prevCapped;
		if (cappedEdge) {
			prevCapped = capped;
			opts.onCapped?.(capped);
		}
		if (parseFloat(el.style.height) !== next) {
			el.style.height = `${next}px`;
			el.style.overflowY = measured > opts.maxPx ? 'auto' : 'hidden';
		} else if (cappedEdge) {
			// 高度恰好不变但跨越 capped 阈值:只需纠正 overflowY
			el.style.overflowY = capped ? 'auto' : 'hidden';
		}
	};

	return {
		schedule(el) {
			if (raf) {
				return;
			}
			raf = requestAnimationFrame(() => run(el));
		},
		cancel() {
			if (raf) {
				cancelAnimationFrame(raf);
				raf = 0;
			}
		},
	};
}
