import {apiUrl} from '@/lib/apiBase';
import {authHeaders} from '@/lib/api/core';

/**
 * 把当前审批模式立即写入会话 RuntimeModeStore（fire-and-forget）。
 *
 * 后端优先级：store 活值 > 请求 body 显式 > config 默认。GUI 在切换处调用，
 * 使**同一轮内尚未执行的下一工具调用**立即按新意图判定，不必等下一轮。
 * 失败静默：不中断当前轮，仅退化为下一轮生效（网络/服务端异常时为可接受的降级）。
 */
export function setSessionRuntimeMode(
	sessionId: string,
	mode: string,
): void {
	if (!sessionId?.trim() || !mode) {
		return;
	}
	void fetch(
		apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/runtime-mode`),
		{
			method: 'POST',
			headers: authHeaders(),
			body: JSON.stringify({permission_mode: mode}),
		},
	).catch(() => {
		// fire-and-forget：写失败不阻塞 UI / 当前回合。
	});
}
