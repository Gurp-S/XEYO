import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout, formatErrorDetail} from '@/lib/api/core';

/**
 * GUI 的 + 快捷菜单技能区数据源。
 *
 * 对应后端 `GET /v1/skills`（`server/routers/skills.py`）：返回结构化技能清单
 * （workspace > home > plugin 三源合并）。只提供**展示与引用**所需的元数据，
 * 不把技能内容塞进提示词——正文仍按 AGENTS.md 走 Skill 工具按需加载。
 *
 * 失败不再返回 `null`：那样调用方只剩"空列表"可渲染，于是**"读不出"被画成
 * "这个工程没有技能"** —— 与后端 `GET /v1/skills` 刚修掉的谎是同一个。
 */

export type SkillSource = 'workspace' | 'home' | 'plugin';

export type SkillInfo = {
	name: string;
	description: string;
	source: SkillSource;
	plugin: string;
	tags: string[];
	model_hint: string;
};

export type SkillsReport = {
	ok: boolean;
	enabled_extensions: boolean;
	skills: SkillInfo[];
	/** 读不出时的原文原因（后端 4xx 的 detail）。 */
	message?: string;
};

export async function fetchSkills(workspace: string): Promise<SkillsReport> {
	try {
		const q = workspace.trim() ? `?workspace=${encodeURIComponent(workspace.trim())}` : '';
		const res = await fetchWithTimeout(apiUrl(`/v1/skills${q}`), {
			headers: authHeaders(),
			cache: 'no-store',
		});
		if (!res.ok) {
			// 只报 "HTTP 422" 等于把人往网络上引，而最常见的原因是工作区目录
			// 已经不存在（工程被改名/移动）——后端把原因写在 detail 里，接住它。
			const payload: unknown = await res.json().catch(() => null);
			return {
				ok: false,
				enabled_extensions: false,
				skills: [],
				message: formatErrorDetail(payload, res.status),
			};
		}
		const payload = (await res.json()) as Partial<SkillsReport>;
		return {
			// 缺 ok 字段算读不出：技能列表为空会被面板念成"这个工作区没有技能"。
			ok: payload.ok === true,
			enabled_extensions: payload.enabled_extensions === true,
			skills: Array.isArray(payload.skills) ? payload.skills : [],
			message: typeof payload.message === 'string' ? payload.message : undefined,
		};
	} catch (err) {
		return {
			ok: false,
			enabled_extensions: false,
			skills: [],
			message: err instanceof Error ? err.message : String(err),
		};
	}
}
