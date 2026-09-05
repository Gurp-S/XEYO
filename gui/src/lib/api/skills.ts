import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout} from '@/lib/api/core';

/**
 * GUI 的 + 快捷菜单技能区数据源。
 *
 * 对应后端 `GET /v1/skills`（`server/routers/skills.py`）：返回结构化技能清单
 * （workspace > home > plugin 三源合并）。只提供**展示与引用**所需的元数据，
 * 不把技能内容塞进提示词——正文仍按 AGENTS.md 走 Skill 工具按需加载。
 *
 * 失败静默：返回 `null`，由调用方渲染空态/错误态，不阻塞菜单其余部分。
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
};

export async function fetchSkills(workspace: string): Promise<SkillsReport | null> {
	try {
		const q = workspace.trim() ? `?workspace=${encodeURIComponent(workspace.trim())}` : '';
		const res = await fetchWithTimeout(apiUrl(`/v1/skills${q}`), {
			headers: authHeaders(),
			cache: 'no-store',
		});
		if (!res.ok) {
			return null;
		}
		const payload = (await res.json()) as Partial<SkillsReport>;
		return {
			ok: payload.ok !== false,
			enabled_extensions: payload.enabled_extensions === true,
			skills: Array.isArray(payload.skills) ? payload.skills : [],
		};
	} catch {
		return null;
	}
}
