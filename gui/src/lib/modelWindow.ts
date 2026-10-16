/**
 * 模型窗口的统一取值：设置登记值优先，其次是厂商 /models 缓存。
 * 面板、请求参数和会话快照共用此口径；已用 token 数仍取厂商或后端实测值。
 * 本模块只依赖设置类型，不读取全局状态。
 */
import type {ModelProfile} from '@/stores/settingsStore';
import {normalizeWindowLimit} from './windowLimit';

export {normalizeWindowLimit} from './windowLimit';

/**
 * 账号里为某个模型登记的上下文窗口（token）。
 *
 * 取值顺序：models[] 里该模型的登记值 → 账号旧版单值字段 profile.contextLimit
 * （兼容迁移前数据、以及在 ModelPicker 里手输未登记的模型名）。
 * 两处都没有 → undefined = 用户根本没登记，绝不猜。
 */
export function registeredContextLimitOf(
	profile: ModelProfile | undefined,
	modelId?: string,
): number | undefined {
	if (!profile) {
		return undefined;
	}
	const id = (modelId ?? profile.model ?? '').trim();
	const rows = Array.isArray(profile.models) ? profile.models : [];
	if (id) {
		const hit = rows.find(m => m.id === id);
		const hitLimit = normalizeWindowLimit(hit?.contextLimit);
		if (hitLimit != null) {
			return hitLimit;
		}
	}
	return normalizeWindowLimit(profile.contextLimit);
}

/**
 * 从 settings 状态切片算「当前激活账号 + 当前激活模型」登记的窗口（token），
 * 未登记 → null。
 *
 * 调用方传入所需的状态切片，避免与 settingsStore 实例耦合。
 */
export function registeredWindowFromSettings(s: {
	profiles: ModelProfile[];
	activeProfileId: string;
	model: string;
}): number | null {
	// 不完整的状态切片按空账号列表处理。
	const list = Array.isArray(s.profiles) ? s.profiles : [];
	const active =
		list.find(p => p.id === s.activeProfileId) ?? list[0];
	if (!active) {
		return null;
	}
	return registeredContextLimitOf(active, s.model) ?? null;
}

/**
 * 窗口分母的优先级裁决：设置登记值 > 厂商 /models 缓存。
 *
 * 用户显式填的值代表意图，且它是「后端压力压缩上限」的同一口径；厂商缓存只在
 * 用户没登记时兜底。两者都缺 → undefined（面板显示「暂无数据」）。
 */
export function resolveWindowLimit(opts: {
	registered?: number | null;
	vendorCached?: number | null;
}): number | undefined {
	return (
		normalizeWindowLimit(opts.registered) ??
		normalizeWindowLimit(opts.vendorCached)
	);
}

/**
 * 上下文占用百分比（0–100，浮点）。分母（窗口）或分子（已用 tokens）未知 →
 * undefined。分母一律由调用方传 resolveWindowLimit 的结果，保证「面板显示的窗口」
 * 与「面板显示的占用%」永远同一分母。
 */
export function windowUsagePercent(opts: {
	contextTokens?: number | null;
	limit?: number | null;
}): number | undefined {
	const limit = normalizeWindowLimit(opts.limit);
	const tokens =
		typeof opts.contextTokens === 'number' &&
		Number.isFinite(opts.contextTokens) &&
		opts.contextTokens >= 0
			? opts.contextTokens
			: undefined;
	if (limit == null || tokens == null) {
		return undefined;
	}
	return Math.min(100, Math.max(0, (tokens / limit) * 100));
}
