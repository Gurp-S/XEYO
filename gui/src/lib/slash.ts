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

/**
 * ghost hint 字典（命令 `hint.<命令名>` 对应物）：claim 激活且参数空白时展示的灰字。
 * 命令在SlashCommand层有 arg_spec 兜底，但中文提示优先走这张表——
 * 新命令未登记时自动回落到 `请输入 <arg_spec>`。
 */
const SLASH_HINTS: Readonly<Record<string, string>> = {
	goal: '请输入目标，智能体将持续执行',
	load: '请输入要恢复的会话 ID',
	export: '请输入导出路径，如 a.md',
	run: '请输入要执行的命令',
	usage: '请输入统计天数，如 7',
	transcript: '请输入导出行数',
	rule: '请输入规则行号',
	ls: '请输入目录路径',
	allow: '请输入权限记录 ID',
	deny: '请输入权限记录 ID',
	diff: '请输入提交/版本号',
	revert: '请输入要回退的提交 ID',
	git: '请输入 git 操作，如 status',
	skills: '请输入技能关键词过滤',
	model: '请输入模型 ID',
	theme: '请输入主题 ID',
	mode: '请输入模式，如 ask / plan',
	output: '请输入输出级别',
	code: '请输入代码级别',
	approval: '请输入审批模式',
	'reasoning-tail': '请输入 tail 模式',
	plugins: '请输入操作，如 list',
};

/** 技能直呼（/<skill_name>）的默认 hint。 */
export const SKILL_GHOST_HINT = '请输入任务，技能将按其流程执行';

/**
 * ghost hint 判定（claim 语义的纯函数化）：
 * 首个词元必须是整段输入的开头（claim = 草稿起点）、精确命中 GUI 命令或技能名、
 * 且其后参数为空白（仅有换行/空格也算未输入）。前缀匹配（输入 "/goa" 中途）不显示。
 * 命中返回提示文案；未知命令/带参/非开头 → null。
 */
export function slashGhostHint(
	value: string,
	skills: ReadonlyArray<{name: string}>,
): string | null {
	const text = value ?? '';
	const m = /^(\/[^\s]+)([\s\S]*)$/.exec(text);
	if (!m) {
		return null;
	}
	if (m[2] !== undefined && m[2].trim() !== '') {
		return null;
	}
	const head = m[1]!.slice(1).toLowerCase();
	if (!head) {
		return null;
	}
	const cmd = slashCommands.find(
		c =>
			c.surfaces.some(s => GUI_SURFACES.includes(s)) &&
			(c.name === head || c.aliases.some(a => a.toLowerCase() === head)),
	);
	if (cmd) {
		return (
			SLASH_HINTS[cmd.name] ??
			(cmd.arg_spec ? `请输入 ${cmd.arg_spec}` : null)
		);
	}
	if (skills.some(s => s.name.toLowerCase() === head)) {
		return SKILL_GHOST_HINT;
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
