/** 紧凑相对时间，类似 Cursor：1m / 2h / 3d */
export function formatRelativeShort(ts: number, now = Date.now()): string {
	const sec = Math.max(0, Math.floor((now - ts) / 1000));
	if (sec < 60) {
		return `${Math.max(1, sec)}s`;
	}
	const min = Math.floor(sec / 60);
	if (min < 60) {
		return `${min}m`;
	}
	const hr = Math.floor(min / 60);
	if (hr < 48) {
		return `${hr}h`;
	}
	const day = Math.floor(hr / 24);
	if (day < 30) {
		return `${day}d`;
	}
	const mo = Math.floor(day / 30);
	return `${mo}mo`;
}
