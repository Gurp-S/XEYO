/** 系统「减少动态」偏好：与产品「流畅」开关对齐。 */

let cached: boolean | null = null;
let mq: MediaQueryList | null = null;

function read(): boolean {
	if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
		return false;
	}
	if (!mq) {
		mq = window.matchMedia('(prefers-reduced-motion: reduce)');
		const sync = () => {
			cached = mq?.matches ?? false;
		};
		sync();
		mq.addEventListener?.('change', sync);
	}
	return cached ?? mq.matches;
}

export function prefersReducedMotion(): boolean {
	return read();
}

/** 供测试重置缓存。 */
export function __resetPrefersReducedMotionCacheForTests() {
	cached = null;
	mq = null;
}
