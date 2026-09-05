/**
 * 统一斜杠命令 —— GUI 面的解析与自动补全。
 *
 * 命令表来自生成物 `@/generated/slashManifest`（单一事实源：
 * python/slash/registry.py，改表后跑 `py -3.11 -m slash.export_manifest`）。
 * 约定：`/` 前缀 = 命令意图；未知命令报错不进模型（主流 Agent 行为）。
 */
import {slashCommands, type SlashCommand} from '@/generated/slashManifest';

const GUI_SURFACES: readonly string[] = ['gui'];

export type SlashParseResult = {
	isSlash: boolean;
	/** 命中 manifest 的命令；未知 /xxx 时为 undefined */
	command?: SlashCommand;
	/** 规范命令名（含未知时的首 token，用于报错文案） */
	name: string;
	arg: string;
	/** / 开头但不在 manifest */
	unknown: boolean;
};

export function parseSlashInput(text: string): SlashParseResult {
	const raw = (text ?? '').trim();
	if (!raw.startsWith('/')) {
		return {isSlash: false, name: '', arg: '', unknown: false};
	}
	const body = raw.slice(1).trim();
	if (!body) {
		return {isSlash: true, name: '', arg: '', unknown: false};
	}
	const [head, rest] = [body.split(/\s+/, 1)[0] ?? '', body.slice((body.split(/\s+/, 1)[0] ?? '').length).trim()];
	const lower = head.toLowerCase();
	const command = slashCommands.find(
		c => c.name === lower || c.aliases.some(a => a.toLowerCase() === lower),
	);
	if (!command) {
		return {isSlash: true, name: head, arg: rest, unknown: true};
	}
	if (!command.surfaces.some(s => GUI_SURFACES.includes(s))) {
		return {isSlash: true, name: head, arg: rest, unknown: true};
	}
	return {isSlash: true, command, name: command.name, arg: rest, unknown: false};
}

export type SlashToken = {
	/** 词元文本（含 / 前缀，不含空白） */
	text: string;
	/** 在原字符串中的区间 [start, end) */
	start: number;
	end: number;
};

/**
 * 触发词元（通用核）：以 trigger 字符开头、且其前是行首或空白的连续非空白串。
 * 用于「消息中途输入 / 或 @」时也能唤起弹层；URL（https://…）、路径（src/foo）
 * 中的 / 因前一个字符非空白而不会误触发。
 */
export function triggerTokenAt(value: string, caret: number, trigger: string): SlashToken | null {
	const text = value ?? '';
	if (!Number.isFinite(caret) || caret < 0 || caret > text.length) {
		return null;
	}
	const esc = trigger.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const m = new RegExp(`(?:^|\\s)([${esc}][^\\s]*)$`).exec(text.slice(0, caret));
	if (!m) {
		return null;
	}
	const start = caret - m[1]!.length;
	let end = caret;
	while (end < text.length && !/\s/.test(text[end]!)) {
		end += 1;
	}
	return {text: text.slice(start, end), start, end};
}

/**
 * 光标所在位置的 slash 词元：以 / 开头、且 / 前是行首或空白的连续非空白串。
 */
export function slashTokenAt(value: string, caret: number): SlashToken | null {
	return triggerTokenAt(value, caret, '/');
}

/** 输入以 / 开头时的候选（前缀匹配 name/别名），按类别排序。 */
export function slashSuggestions(input: string): SlashCommand[] {
	const raw = (input ?? '').trim();
	if (!raw.startsWith('/')) {
		return [];
	}
	const p = raw.slice(1).trim().toLowerCase();
	if (p.includes(' ')) {
		return [];
	}
	return slashCommands
		.filter(
			c =>
				c.surfaces.some(s => GUI_SURFACES.includes(s)) &&
				(c.name.startsWith(p) || c.aliases.some(a => a.toLowerCase().startsWith(p))),
		)
		.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
}

export type SlashTokenColor = 'command' | 'skill';

/**
 * / 词元的着色类别：命中 GUI 命令（name/别名）→ command（橙），
 * 命中技能名 → skill（蓝）。精确命中优先于前缀（输入过程中即可着色），
 * 都不命中返回 null（不着色，例如 URL/路径中的斜杠词元）。
 */
export function slashLeadingColor(
	head: string,
	skills: ReadonlyArray<{name: string}>,
): SlashTokenColor | null {
	const h = (head ?? '').trim().toLowerCase();
	if (!h) {
		return null;
	}
	const isGuiCmd = (c: SlashCommand) =>
		c.surfaces.some(s => GUI_SURFACES.includes(s));
	if (
		slashCommands.some(
			c => isGuiCmd(c) && (c.name === h || c.aliases.some(a => a.toLowerCase() === h)),
		)
	) {
		return 'command';
	}
	if (skills.some(s => s.name.toLowerCase() === h)) {
		return 'skill';
	}
	if (
		slashCommands.some(
			c =>
				isGuiCmd(c) &&
				(c.name.startsWith(h) || c.aliases.some(a => a.toLowerCase().startsWith(h))),
		)
	) {
		return 'command';
	}
	if (skills.some(s => s.name.toLowerCase().startsWith(h))) {
		return 'skill';
	}
	return null;
}

const CATEGORY_ZH: Record<string, string> = {
	meta: '通用',
	session: '会话',
	mode: '配置',
	info: '状态',
	control: '控制',
	memory: '记忆',
	tool: '工具',
	extension: '扩展',
	demo: '演示',
};

/** /help 渲染文案（按 GUI 可用面过滤，类别分组）。 */
export function formatSlashHelp(): string {
	const groups = new Map<string, string[]>();
	for (const c of slashCommands) {
		if (!c.surfaces.some(s => GUI_SURFACES.includes(s))) {
			continue;
		}
		const alias = c.aliases.length ? `（${c.aliases.slice(0, 3).join('/')}）` : '';
		const key = CATEGORY_ZH[c.category] ?? c.category;
		const list = groups.get(key) ?? [];
		list.push(`${c.usage}  ${c.summary}${alias}`);
		groups.set(key, list);
	}
	const lines: string[] = ['可用斜杠命令：'];
	for (const key of [...groups.keys()].sort()) {
		lines.push(`● ${key}`);
		lines.push(...(groups.get(key) ?? []));
	}
	return lines.join('\n');
}
