/**
 * modelWindow.ts — 「模型窗口」的唯一口径（纯函数、可单测、零 store 依赖）。
 *
 * 为什么存在：聊天顶部用量面板的窗口分母曾经只从「会话累计 usage 快照」里取
 * （厂商回传的 context_limit），于是出现三种填了设置却不变的形态——
 * ① 新会话还没有任何 usage → 面板无处可取；② 换账号 / 换模型 → 旧快照残留；
 * ③ 用户在设置里改窗口 → 要等下一次请求厂商回传才覆盖。
 * 本模块把取值口径定成一条：**用户在设置里登记的窗口优先**，厂商 /models 缓存
 * 兜底，两者都没有才叫「窗口未知」。面板、发给后端的 context_limit、以及回填
 * 会话快照的 sync 全部走这一条，不再各算各的。
 *
 * 注意：这里只解决「窗口是多少」，不解决「已用多少」——分子（context_tokens）
 * 永远是厂商/后端实测值，不随设置变。
 */
import type {ModelProfile} from '@/stores/settingsStore';

/** 归一化为正整数窗口；非法 / 空 / <=0 → undefined（调用方不得当 0 或猜值）。 */
export function normalizeWindowLimit(v: unknown): number | undefined {
	if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) {
		return undefined;
	}
	return Math.floor(v);
}

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
 * 住在纯模块而不是 settingsStore：ChatHeader 等消费方经 useSettingsStore 取状态
 * 即可，不必 import store 里的新符号——测试替身（src/test/setup.ts 的
 * vi.mock('@/stores/settingsStore')）只需喂 profiles/activeProfileId/model 字段，
 * 不会因为替身导出面缺一个函数而炸掉渲染 ChatHeader 的集成测试。
 */
export function registeredWindowFromSettings(s: {
	profiles: ModelProfile[];
	activeProfileId: string;
	model: string;
}): number | null {
	// Array 守卫：profiles 在真 store 里恒为数组，但渲染 ChatHeader 的测试替身
	// 可能只喂一半字段（src/test/setup.ts 有 profiles，个别 test 文件的局部替身没有）。
	// 少一个字段就抛 TypeError 会把整棵渲染树打死（同类事故见 ModelPicker 的红测试）。
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
