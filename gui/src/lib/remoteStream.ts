/** 用 status 的 stream_from 增量拼回完整草稿。 */

export function assembleStream(opts: {
	acc: string;
	from: number;
	chunk: string;
	serverLen: number;
	reset?: boolean;
}): {acc: string; from: number} {
	const chunk = opts.chunk || '';
	const serverLen = Number.isFinite(opts.serverLen) ? opts.serverLen : 0;
	if (opts.reset || opts.from > serverLen) {
		return {acc: chunk, from: serverLen};
	}
	return {acc: opts.acc.slice(0, opts.from) + chunk, from: serverLen};
}
