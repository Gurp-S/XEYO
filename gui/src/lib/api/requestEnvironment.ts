import {useSettingsStore} from '@/stores/settingsStore';
import {useBrowserPreviewStore} from '@/stores/browserPreviewStore';
import {workspaceActiveTool} from '@/stores/storeRefs';
import {getCachedModelContextLimit} from './usage';
import {registeredContextLimitOf, resolveWindowLimit} from '@/lib/modelWindow';
import type {ChatRequestOptions} from './core';

/** 浏览器预览面板打开且已加载 URL 时，供 LLM T_now 感知（省 token：无则不上报）。 */
function browserPreviewUrlForChat(): string | undefined {
	if (workspaceActiveTool() !== 'browser') {
		return undefined;
	}
	const url = useBrowserPreviewStore.getState().url?.trim();
	return url || undefined;
}

export function currentRequestEnvironment(options?: ChatRequestOptions, clearMissing = false) {
	const s = useSettingsStore.getState();
	const unset = clearMissing ? null : undefined;
	// 上下文窗口：与聊天顶部用量面板同一口径（@/lib/modelWindow）——**设置里为
	// 该模型登记的窗口优先**（用户在账号里显式填的值就是他的意图，也是设置页承诺
	// 的「窗口分母 + 后端压力压缩上限」），厂商 /models 缓存只在未登记时兜底。
	// 曾经这里是厂商缓存优先 + 只读账号旧单值字段 profile.contextLimit，于是
	// ①多模型账号下永远发的是账号级旧值、②面板与后端两侧数字打架。
	const activeProfile = s.profiles.find(p => p.id === s.activeProfileId);
	const contextLimit = resolveWindowLimit({
		registered: registeredContextLimitOf(activeProfile, s.model),
		vendorCached: getCachedModelContextLimit(
			s.provider,
			s.resolvedBaseUrl(),
			s.model,
		),
	});
	// 最大输出 tokens：优先账号里保存的值；无则不发送（不限制）。
	const maxOutputTokens =
		typeof activeProfile?.maxOutputTokens === 'number' &&
		Number.isFinite(activeProfile.maxOutputTokens) &&
		activeProfile.maxOutputTokens > 0
			? activeProfile.maxOutputTokens
			: undefined;
	// 思考等级优先级：输入框手动选（options.reasoningEffort）> 模型默认等级 > 会话级。
	// 模型默认等级跌出该模型已登记支持集（历史遗留数据）→ 跳过该默认，避免发出
	// 模型不支持的 reasoning_effort。
	const activeModel =
		activeProfile?.models?.find(m => m.id === s.model);
	const modelDefaultEffort = activeModel?.defaultReasoningEffort || '';
	const modelDefaultSupported =
		!modelDefaultEffort ||
		!(activeModel?.reasoningLevels?.length) ||
		(activeModel?.reasoningLevels ?? []).includes(modelDefaultEffort);
	const defaultEffort =
		(modelDefaultSupported ? modelDefaultEffort : '') || s.reasoningEffort || '';
	const reasoningEffort =
		(options?.reasoningEffort?.trim() || defaultEffort) || undefined;
	// 思考开关与等级是成对的：选了等级就必须开 thinking，否则后端收不到
	// reasoning_effort（DeepSeek 要求 `thinking.type==="enabled"` 才发等级）。
	// 用户显式关思考时等级一并作废，避免发出「关了思考却带等级」的矛盾请求。
	const thinking: 'enabled' | 'disabled' =
		s.thinking === 'enabled' || reasoningEffort ? 'enabled' : 'disabled';
	const effectiveEffort = thinking === 'enabled' ? reasoningEffort : undefined;
	const previewUrl = browserPreviewUrlForChat();
	return {
		model: s.model, provider: s.provider, base_url: s.resolvedBaseUrl(),
		context_limit: contextLimit ?? unset, max_tokens: maxOutputTokens ?? unset, thinking,
		reasoning_effort: effectiveEffort ?? unset,
		max_budget_usd: s.maxBudgetUsd ? Number(s.maxBudgetUsd) : unset,
		permission_mode: s.permissionMode,
		output_compact: s.outputCompact === true, output_mode: s.outputCompact ? s.outputMode : unset,
		code_compact: s.codeCompact === true, code_mode: s.codeCompact ? s.codeMode : unset,
		browser_preview_url: previewUrl ?? unset,
		searxng_url: s.searxngUrl?.trim() || unset,
		agent_mode: options?.agentMode ?? 'agent', multi_agent: options?.multiAgent ?? false,
	};
}
