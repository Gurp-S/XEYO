/**
 * 统一斜杠命令 —— GUI 面的执行层。
 *
 * - client 命令：本地改 store / 触发回调，不发请求、不进模型。
 * - server 命令：POST /v1/slash（后端 slash.dispatch），结果以 UI-only 系统行回显。
 * - 未知 /xxx：报错不进模型（主流 Agent 行为）。
 * 模式/精简类开关只改请求体来源（settingsStore / chatUiStore），符合 AGENTS.md
 * 的 T_now 范式（下一轮请求生效，不写历史、不进 system）。
 */
import {slashCommands, type SlashCommand} from '@/generated/slashManifest';
import {apiUrl} from '@/lib/apiBase';
import {fetchSkills, type SkillInfo} from '@/lib/api';
import {formatSlashHelp, parseSlashInput} from '@/lib/slash';
import {useSettingsStore, type OutputMode, type PermissionMode} from '@/stores/settingsStore';
import {normalizeThemeId} from '@/theme/catalog';
import {useChatStore} from '@/stores/chatStore';

export type SlashRunOutcome =
	| {status: 'not-slash'}
	| {status: 'unknown'; name: string}
	/** 已本地处理；text 非空则回显系统行 */
	| {status: 'local'; text: string}
	/** server 命令已执行；text 为结果（可能为空） */
	| {status: 'server'; text: string}
	/** 改发这段文本（/run → 交给模型用 Bash 工具） */
	| {status: 'send'; text: string};

export type SlashRunOptions = {
	/** 本地 UI 会话 id */
	sessionId: string;
	/** 后端 Agent 会话 id（用于 /v1/slash） */
	backendSessionId?: string;
	/** 工作区根（用于 /v1/slash） */
	workspace: string;
	/** /clear：新建会话 */
	onNewSession: () => void;
	/** /retry：重发上一条用户消息 */
	onRetryLast: () => void;
};

const OUTPUT_LEVELS = new Set(['lite', 'full', 'ultra']);
const PERMISSION_MODES = new Set<PermissionMode>(['always', 'risk', 'never']);

/** 技能清单缓存（按 workspace），供「/技能名」直呼解析，避免每次发送都拉取。 */
const skillListCache = new Map<string, SkillInfo[]>();

async function findSkillByName(
	head: string,
	workspace: string,
): Promise<SkillInfo | null> {
	const want = head.trim().toLowerCase();
	if (!want) {
		return null;
	}
	const key = workspace || '';
	let skills = skillListCache.get(key);
	if (!skills) {
		try {
			const report = await fetchSkills(key);
			if (!report || report.ok === false) {
				return null;
			}
			skills = report.skills;
		} catch {
			return null;
		}
		skillListCache.set(key, skills);
	}
	return skills.find(s => s.name.toLowerCase() === want) ?? null;
}

async function postSlash(
	command: SlashCommand,
	arg: string,
	opts: SlashRunOptions,
): Promise<string> {
	const s = useSettingsStore.getState();
	const provider = s.provider === 'local' ? 'deepseek' : s.provider;
	const res = await fetch(apiUrl('/v1/slash'), {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			...(s.apiKey ? {Authorization: `Bearer ${s.apiKey}`} : {}),
		},
		body: JSON.stringify({
			name: command.name,
			arg,
			session_id: opts.backendSessionId || opts.sessionId,
			workspace: opts.workspace,
			provider,
			base_url: s.baseUrl?.trim() || undefined,
			model: s.model || undefined,
		}),
	});
	if (!res.ok) {
		throw new Error(`HTTP ${res.status}`);
	}
	const data = (await res.json()) as {
		handled: boolean;
		message?: string;
		result?: {message?: string} | null;
	};
	if (data.result && typeof data.result.message === 'string' && data.result.message) {
		return data.result.message;
	}
	return data.message ?? '';
}

function localLevel(lvl: string): {on: boolean; mode: OutputMode} {
	const l = lvl.trim().toLowerCase();
	if (l === 'off' || l === '关') {
		return {on: false, mode: 'lite'};
	}
	if (OUTPUT_LEVELS.has(l)) {
		return {on: true, mode: l as OutputMode};
	}
	return {on: true, mode: 'lite'};
}

export async function runSlashCommand(
	raw: string,
	opts: SlashRunOptions,
): Promise<SlashRunOutcome> {
	const parsed = parseSlashInput(raw);
	if (!parsed.isSlash) {
		return {status: 'not-slash'};
	}
	if (parsed.unknown || !parsed.command) {
		// 技能直呼（Composer 技能候选插入的就是 /<skill_name>）：
		// - /name        → /skills show <name>（回显技能卡片）
		// - /name 任务…  → 发送即原文（dsh plain-text 决策）：原样进模型，
		//   由宿主 skill_preinvoke（engine/skill_preinvoke.py）识别首行 /name
		//   并确定性注入 SKILL.md 正文——不再赌模型自觉调 Skill 工具。
		const skill = await findSkillByName(parsed.name, opts.workspace);
		if (skill) {
			const rest = parsed.arg.trim();
			if (!rest) {
				const skillsCmd = slashCommands.find(c => c.name === 'skills');
				if (skillsCmd) {
					try {
						const text = await postSlash(skillsCmd, `show ${skill.name}`, opts);
						return {status: 'server', text};
					} catch (err) {
						return {
							status: 'server',
							text: `/skills 执行失败：${err instanceof Error ? err.message : String(err)}`,
						};
					}
				}
				return {status: 'unknown', name: parsed.name};
			}
			return {status: 'send', text: raw};
		}
		return {status: 'unknown', name: parsed.name};
	}
	const command = parsed.command;
	const arg = parsed.arg;

	switch (command.name) {
		// ---------------- client：本地完成 ----------------
		case 'help':
			return {status: 'local', text: formatSlashHelp()};
		case 'version':
			return {status: 'local', text: 'XEYO GUI（版本随构建打包）'};
		case 'docs':
			return {status: 'local', text: '文档见仓库 docs/ 目录（docs/README.md 有索引）。'};
		case 'clear':
			opts.onNewSession();
			return {status: 'local', text: '已新建会话。'};
		case 'retry':
			opts.onRetryLast();
			return {status: 'local', text: ''};
		case 'run': {
			const cmdText = arg.trim();
			if (!cmdText) {
				return {status: 'local', text: '用法：/run <command>'};
			}
			return {
				status: 'send',
				text:
					'[slash:/run] 请用 Bash 工具执行以下命令并汇总结果（遵守权限门禁，' +
					'不要执行无关命令）：\n\n' +
					cmdText,
			};
		}
		case 'mode': {
			const m = arg.trim().toLowerCase();
			if (m !== 'agent' && m !== 'plan' && m !== 'ask') {
				return {status: 'local', text: '用法：/mode <agent|plan|ask>'};
			}
			useChatStore.getState().setAgentMode(m);
			return {status: 'local', text: `mode → ${m}`};
		}
		case 'output':
		case 'code': {
			const {on, mode} = localLevel(arg);
			const patch =
				command.name === 'output'
					? {outputCompact: on, outputMode: mode}
					: {codeCompact: on, codeMode: mode};
			useSettingsStore.getState().update(patch);
			const which = command.name === 'output' ? '输出精简' : '写代码精简';
			return {
				status: 'local',
				text: `${which} ${on ? 'on' : 'off'}${on ? `（${mode}）` : ''}`,
			};
		}
		case 'approval': {
			const m = arg.trim().toLowerCase() as PermissionMode;
			if (!PERMISSION_MODES.has(m)) {
				return {status: 'local', text: '用法：/approval <always|risk|never>'};
			}
			useSettingsStore.getState().update({permissionMode: m});
			return {status: 'local', text: `审批模式 → ${m}`};
		}
		case 'model': {
			const id = arg.trim();
			if (!id) {
				return {status: 'local', text: '用法：/model <model_id>'};
			}
			useSettingsStore.getState().update({model: id});
			return {status: 'local', text: `model → ${id}（下一轮生效）`};
		}
		case 'theme': {
			const id = arg.trim();
			if (!id) {
				return {status: 'local', text: '用法：/theme <theme_id>'};
			}
			useSettingsStore.getState().update({theme: normalizeThemeId(id)});
			return {status: 'local', text: `theme → ${normalizeThemeId(id)}`};
		}
		case 'exit':
		case 'demo':
		case 'load':
			return {
				status: 'local',
				text: command.name === 'load' ? 'GUI 请用侧栏切换会话。' : '该命令仅 CLI 提供。',
			};
		// ---------------- server：POST /v1/slash ----------------
		default: {
			if (command.handler !== 'server') {
				return {status: 'local', text: `/${command.name} 暂未实现。`};
			}
			try {
				const text = await postSlash(command, arg, opts);
				return {status: 'server', text};
			} catch (err) {
				return {
					status: 'server',
					text: `/${command.name} 执行失败：${err instanceof Error ? err.message : String(err)}`,
				};
			}
		}
	}
}

/** Composer 调用入口：处理命令并回显；返回是否消费了这条输入。 */
export async function handleComposerSlash(
	value: string,
	opts: SlashRunOptions,
): Promise<boolean> {
	const probe = parseSlashInput(value);
	if (!probe.isSlash) {
		return false;
	}
	const chat = useChatStore.getState();
	chat.appendLocalNote?.(`> ${value.trim()}`);
	const outcome = await runSlashCommand(value, opts);
	switch (outcome.status) {
		case 'not-slash':
			return false;
		case 'unknown':
			chat.appendLocalNote?.(`未知命令 /${outcome.name}，试试 /help`);
			return true;
		case 'send':
			// /run：命令行已回显；改发提示词（去掉上面的回显行，正文再补一条用户气泡由 sendMessage 负责）
			void chat.sendMessage(outcome.text, [], [], undefined);
			return true;
		case 'local':
		case 'server':
			if (outcome.text) {
				chat.appendLocalNote?.(outcome.text);
			}
			return true;
		default:
			return true;
	}
}

/** 供 /retry 找上一条用户消息（Composer 也可直接复用）。 */
export function lastUserText(sessionId: string): string {
	const msgs = useChatStore.getState().messagesById[sessionId] ?? [];
	for (let i = msgs.length - 1; i >= 0; i -= 1) {
		const m = msgs[i];
		if (m && m.role === 'user' && m.text.trim() && !m.uiOnly) {
			return m.text;
		}
	}
	return '';
}
