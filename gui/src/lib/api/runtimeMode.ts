import {apiUrl} from '@/lib/apiBase';
import {authHeaders, formatErrorDetail} from '@/lib/api/core';

/**
 * 把当前审批模式立即写入会话 RuntimeModeStore。
 *
 * 后端优先级：store 活值 > 请求 body 显式 > config 默认 —— 也就是说
 * **只要这个会话有过一次成功的写入，body 里的值就再也说不上话**，
 * 本函数是改变当前会话判定档的唯一通道。
 *
 * 旧实现是 fire-and-forget（注释写"失败静默，退化为下一轮生效"），那句话不成立：
 * 403（loopback 门禁）/ 400（非法档）/ 后端没起时，活值仍是旧档，下一轮也不会有变化，
 * 而按钮已经按新档画出来了。权限面上"以为收紧了"和"以为放开了"都是要命的读数。
 * 所以这里必须可 await 并带回回执，由调用方决定怎么标"未确认"。
 */
export type RuntimeModeWrite = {ok: boolean; mode: string; message: string};

export async function setSessionRuntimeMode(
	sessionId: string,
	mode: string,
): Promise<RuntimeModeWrite> {
	if (!sessionId?.trim()) {
		return {ok: false, mode: '', message: 'no_session'};
	}
	if (!mode?.trim()) {
		return {ok: false, mode: '', message: 'no_mode'};
	}
	const want = mode.trim();
	try {
		const res = await fetch(
			apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/runtime-mode`),
			{
				method: 'POST',
				headers: {
					...authHeaders(),
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({permission_mode: want}),
			},
		);
		const payload = await res.json().catch(() => null);
		if (!res.ok) {
			return {ok: false, mode: '', message: formatErrorDetail(payload, res.status)};
		}
		const body = payload as {
			ok?: unknown;
			permission_mode?: unknown;
			effective?: unknown;
		} | null;
		if (!body || typeof body !== 'object' || body.ok !== true) {
			return {
				ok: false,
				mode: '',
				message:
					body && typeof body === 'object'
						? formatErrorDetail(payload, res.status)
						: 'receipt_not_object',
			};
		}
		if (typeof body.permission_mode !== 'string' || !body.permission_mode.trim()) {
			return {ok: false, mode: '', message: 'receipt_missing_mode'};
		}
		const got = body.permission_mode.trim();
		if (got !== want) {
			// 后端归一化成了别的档：引擎按 got 判定，UI 不能报 want。
			return {
				ok: false,
				mode: got,
				message: `后端记的是 ${got}，与请求的 ${want} 不一致`,
			};
		}
		if (body.effective != null && String(body.effective).trim() !== got) {
			return {
				ok: false,
				mode: got,
				message: `回执自报生效值是 ${String(body.effective).trim()}，与写入档 ${got} 不一致`,
			};
		}
		return {ok: true, mode: got, message: ''};
	} catch (err) {
		return {
			ok: false,
			mode: '',
			message: err instanceof Error ? err.message : String(err),
		};
	}
}
