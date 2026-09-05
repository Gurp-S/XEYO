/** 流畅开启时始终挂载最新若干 round；更早的进视口再挂。 */
export const ALWAYS_MOUNT_LATEST = 2;

export function shouldMountRound(opts: {
	index: number;
	total: number;
	smoothness: boolean;
	forced?: boolean;
	/** jsdom 无 IntersectionObserver 时挂载全部，避免测试看不到历史。 */
	ioAvailable?: boolean;
}): boolean {
	if (!opts.smoothness) {
		return true;
	}
	if (opts.forced) {
		return true;
	}
	if (opts.ioAvailable === false) {
		return true;
	}
	return opts.index >= opts.total - ALWAYS_MOUNT_LATEST;
}
