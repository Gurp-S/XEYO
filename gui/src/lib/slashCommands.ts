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
import {fetchSkills, fetchWithTimeout, type SkillInfo, type SkillsReport} from '@/lib/api';
import {formatSlashHelp, parseSlashInput} from '@/lib/slash';
import {syncGoalAfterCommand} from '@/lib/goalSync';
import {useSettingsStore, type OutputMode, type PermissionMode} from '@/stores/settingsStore';
import {normalizeThemeId} from '@/theme/catalog';
import {useChatStore} from '@/stores/chatStore';
import {
	getSessionStream,
	isSessionStreamLive,
	sessionStreamActive,
} from '@/lib/sessionStreams';
import {toast} from '@/lib/toast';

export type SlashRunOutcome =
	| {status: 'not-slash'}
	| {status: 'unknown'; name: string}
	/** 命令已识别但未成功执行；Composer 显示原因并保留输入。 */
	| {status: 'rejected'; text?: string}
	/** 已本地处理；text 非空则回显系统行 */
	| {status: 'local'; text: string}
	/** server 命令已执行；text 为结果（可能为空） */
	| {status: 'server'; text: string}
	/** 作为用户消息发送（例如 /run）；保留用户原文。 */
	| {status: 'send'; text: string};

export type SlashRunOptions = {
	/** 本地 UI 会话 id */
	sessionId: string;
	/** 后端 Agent 会话 id（用于 /v1/slash） */
	backendSessionId?: string;
	/** 工作区根（用于 /v1/slash） */
	workspace: string;
	/** 当前会话是否有未结束的生成；遵守 manifest 的 when 门禁。 */
	sessionBusy?: boolean;
	/** /clear：新建会话 */
	onNewSession: () => void | Promise<unknown>;
	/** /retry：重发上一条用户消息 */
	onRetryLast: () => boolean | void | Promise<boolean | void>;
	/** 将技能或改写命令送入常规聊天发送链路；返回值表示消息已被接受。 */
	onSend?: (text: string) => Promise<boolean> | boolean;
	/** 供非 Composer 调用方呈现完整执行结果；不改变统一处理语义。 */
	onOutcome?: (outcome: SlashRunOutcome) => void;
};

const OUTPUT_LEVELS = new Set(['lite', 'full', 'ultra']);
const PERMISSION_MODES = new Set<PermissionMode>(['always', 'risk', 'never']);

/** 技能候选与提交解析共用同一份短时缓存，避免 UI 命中后提交时重复拉取。 */
const SKILL_CACHE_TTL_MS = 15_000;
const EMPTY_SKILL_CACHE_TTL_MS = 2_000;
const skillListCache = new Map<
	string,
	{report: SkillsReport; expiresAt: number}
>();
const skillListRequests = new Map<string, Promise<SkillsReport>>();

/** 测试专用：技能候选缓存与在途请求是模块级状态，跨用例必须能清空。 */
export function resetSlashSkillCacheForTests(): void {
	skillListCache.clear();
	skillListRequests.clear();
}

export function cachedSlashSkills(workspace: string): SkillsReport | null {
	const key = workspace.trim();
	const entry = skillListCache.get(key);
	if (!entry) return null;
	if (entry.expiresAt <= Date.now()) {
		skillListCache.delete(key);
		return null;
	}
	return entry.report;
}

export function loadSlashSkills(workspace: string): Promise<SkillsReport> {
	const key = workspace.trim();
	const cached = cachedSlashSkills(key);
	if (cached) return Promise.resolve(cached);
	const pending = skillListRequests.get(key);
	if (pending) return pending;
	const request = fetchSkills(key)
		.catch(err => ({
			ok: false,
			enabled_extensions: false,
			skills: [],
			message: err instanceof Error ? err.message : String(err),
		}))
		.then(report => {
			if (report.ok) {
				skillListCache.set(key, {
					report,
					expiresAt:
						Date.now() +
						(report.skills.length > 0
							? SKILL_CACHE_TTL_MS
							: EMPTY_SKILL_CACHE_TTL_MS),
				});
			}
			return report;
		})
		.finally(() => {
			if (skillListRequests.get(key) === request) {
				skillListRequests.delete(key);
			}
		});
	skillListRequests.set(key, request);
	return request;
}

async function findSkillByName(
	head: string,
	workspace: string,
): Promise<{skill: SkillInfo | null; error?: string}> {
	const want = head.trim().toLowerCase();
	if (!want) {
		return {skill: null};
	}
	if (!workspace.trim()) {
		// An omitted workspace makes /v1/skills use the server's global UI cwd.
		return {skill: null};
	}
	const report = await loadSlashSkills(workspace);
	if (!report.ok) {
		return {skill: null, error: report.message || '技能清单暂不可用'};
	}
	return {skill: report.skills.find(s => s.name.toLowerCase() === want) ?? null};
}

async function postSlash(
	command: SlashCommand,
	arg: string,
	opts: SlashRunOptions,
): Promise<string> {
	const s = useSettingsStore.getState();
	const provider = s.provider === 'local' ? 'deepseek' : s.provider;
	const res = await fetchWithTimeout(apiUrl('/v1/slash'), {
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
		const payload = (await res.json().catch(() => null)) as {
			detail?: unknown;
			message?: unknown;
		} | null;
		const detail =
			typeof payload?.detail === 'string'
				? payload.detail
				: typeof payload?.message === 'string'
					? payload.message
					: '';
		throw new Error(detail || `HTTP ${res.status}`);
	}
	const data = (await res.json()) as {
		handled?: boolean;
		message?: string;
		result?: {message?: string} | null;
	};
	if (data.handled !== true) {
		throw new Error(data.message?.trim() || `/${command.name} 未执行`);
	}
	if (data.result && typeof data.result.message === 'string' && data.result.message) {
		return data.result.message;
	}
	return data.message ?? '';
}

function localLevel(lvl: string): {on: boolean; mode: OutputMode} | null {
	const l = lvl.trim().toLowerCase();
	if (l === 'off' || l === '关') {
		return {on: false, mode: 'lite'};
	}
	if (OUTPUT_LEVELS.has(l)) {
		return {on: true, mode: l as OutputMode};
	}
	return l ? null : {on: true, mode: 'lite'};
}

export async function runSlashCommand(
	raw: string,
	opts: SlashRunOptions,
): Promise<SlashRunOutcome> {
	const parsed = parseSlashInput(raw);
	if (!parsed.isSlash) {
		return {status: 'not-slash'};
	}
	if (!parsed.name) {
		return {status: 'rejected', text: '命令名不能为空，输入 /help 查看可用命令。'};
	}
	if (parsed.unknown || !parsed.command) {
		const knownOnAnotherSurface = slashCommands.find(
			command =>
				(command.name === parsed.name.toLowerCase() ||
					command.aliases.some(alias => alias.toLowerCase() === parsed.name.toLowerCase())) &&
				!command.surfaces.includes('gui'),
		);
		if (knownOnAnotherSurface) {
			const detail =
				knownOnAnotherSurface.name === 'load'
					? 'GUI 请用侧栏切换会话。'
					: '该命令仅 CLI / TUI 提供。';
			return {status: 'local', text: `/${knownOnAnotherSurface.name}：${detail}`};
		}
		// 技能直呼（Composer 技能候选插入的就是 /<skill_name>）：
		// - /name        → /skills show <name>（回显技能卡片）
		// - /name 任务…  → 发送即原文（plain-text 决策）：原样进模型，
		//   由宿主 skill_preinvoke（engine/skill_preinvoke.py）识别首行 /name
		//   并确定性注入 SKILL.md 正文——不再赌模型自觉调 Skill 工具。
		const {skill, error} = await findSkillByName(parsed.name, opts.workspace);
		if (error) {
			return {
				status: 'rejected',
				text: `技能清单读取失败：${error}`,
			};
		}
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
							status: 'rejected',
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
	const chatState = useChatStore.getState();
	const stream = getSessionStream(chatState, opts.sessionId);
	const sessionBusy =
		Boolean(opts.sessionBusy) ||
		sessionStreamActive(chatState, opts.sessionId) ||
		isSessionStreamLive(stream);
	if (command.when === 'idle' && sessionBusy) {
		return {
			status: 'rejected',
			text: `会话仍在运行，/${command.name} 暂不可执行；可用 /stop 中断当前回合。`,
		};
	}

	switch (command.name) {
		// ---------------- client：本地完成 ----------------
		case 'help':
			return {status: 'local', text: formatSlashHelp()};
		case 'version':
			return {status: 'local', text: 'XEYO GUI（版本随构建打包）'};
		case 'docs':
			return {status: 'local', text: '文档见仓库 docs/ 目录（架构图与评测结果）。'};
		case 'clear':
			await opts.onNewSession();
			return {status: 'local', text: '已新建会话。'};
		case 'retry':
			if ((await opts.onRetryLast()) === false) {
				return {status: 'rejected'};
			}
			return {status: 'local', text: ''};
		case 'run': {
			const cmdText = arg.trim();
			if (!cmdText) {
				return {status: 'rejected', text: '用法：/run <command>'};
			}
			return {status: 'send', text: raw};
		}
		case 'mode': {
			const m = arg.trim().toLowerCase();
			if (m !== 'agent' && m !== 'plan' && m !== 'ask') {
				return {status: 'rejected', text: '用法：/mode <agent|plan|ask>'};
			}
			useChatStore.getState().setAgentMode(m);
			return {status: 'local', text: `mode → ${m}`};
		}
		case 'output':
		case 'code': {
			const level = localLevel(arg);
			if (!level) {
				return {status: 'rejected', text: `用法：${command.usage}`};
			}
			const {on, mode} = level;
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
				return {status: 'rejected', text: '用法：/approval <always|risk|never>'};
			}
			useSettingsStore.getState().update({permissionMode: m});
			return {status: 'local', text: `审批模式 → ${m}`};
		}
		case 'model': {
			const id = arg.trim();
			if (!id) {
				return {status: 'rejected', text: '用法：/model <model_id>'};
			}
			useSettingsStore.getState().update({model: id});
			return {status: 'local', text: `model → ${id}（下一轮生效）`};
		}
		case 'theme': {
			const id = arg.trim();
			if (!id) {
				return {status: 'rejected', text: '用法：/theme <theme_id>'};
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
				// /goal 创建成功后主动同步投影 + 显式 arm：/v1/slash 不产生 SSE goal 帧，
				// 不发消息 → 没有 chat turn → store 为空 → GoalDock（按 store 挂载）永不显示。
				// 详见 lib/goalSync.ts 头注释（2026-09-05 调查报告 §10-④）。
				if (command.name === 'goal' && opts.sessionId) {
					const sync = await syncGoalAfterCommand(
						opts.sessionId,
						opts.backendSessionId,
					);
					if (!sync.ok) {
						// 后端那句"已创建"是真的，但界面没挂出目标、也没上自动续跑：
						// 只回前半句就是让用户按一个没验证过的状态行动。
						return {status: 'server', text: `${text}\n${sync.note}`};
					}
				}
				return {status: 'server', text};
			} catch (err) {
				return {
					status: 'rejected',
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
	// 语义：composer 永不回显命令行——命令事实由结果回执卡片承载
	// （见下方 noteKind:'cmd'），聊天流里不再出现 `> /cmd` 裸回显。
	const outcome = await runSlashCommand(value, opts);
	opts.onOutcome?.(outcome);
	switch (outcome.status) {
		case 'not-slash':
			return false;
		case 'unknown':
			if (opts.sessionId) {
				chat.appendLocalNote?.(`未知命令 /${outcome.name}，试试 /help`, {
					sessionId: opts.sessionId,
				});
			} else {
				toast.error(`未知命令 /${outcome.name}，试试 /help`);
			}
			// 保留草稿，方便原位修正拼错的命令；未知命令仍不会进入模型。
			return false;
		case 'rejected':
			if (outcome.text) {
				if (opts.sessionId) {
					chat.appendLocalNote?.(outcome.text, {
						kind: 'cmd',
						title: value.trim(),
						sessionId: opts.sessionId,
					});
				} else {
					toast.error(outcome.text);
				}
			}
			return false;
		case 'send':
			// 发送用户原文；用户气泡由 sendMessage 负责。
			if (opts.onSend) {
				return await opts.onSend(outcome.text);
			}
			const accepted = await chat.sendMessage(
				outcome.text,
				[],
				[],
				undefined,
				undefined,
				undefined,
				{
					sessionId: opts.sessionId,
					background: useChatStore.getState().activeId !== opts.sessionId,
				},
			);
			if (!accepted) toast.error('目标会话未接受该命令消息');
			return accepted;
		case 'local':
		case 'server':
			if (outcome.text) {
				const resultSessionId =
					probe.command?.name === 'clear'
						? useChatStore.getState().activeId ?? opts.sessionId
						: opts.sessionId;
				if (resultSessionId) {
					chat.appendLocalNote?.(outcome.text, {
						kind: 'cmd',
						title: value.trim(),
						sessionId: resultSessionId,
					});
				} else {
					toast.info(outcome.text);
				}
			}
			return true;
		default:
			return true;
	}
}

/** 供 /retry 找上一条完整用户输入（包含已上传的图片引用）。 */
export function lastUserMessage(
	sessionId: string,
): {text: string; mediaRefs: string[]} | null {
	const msgs = useChatStore.getState().messagesById[sessionId] ?? [];
	for (let i = msgs.length - 1; i >= 0; i -= 1) {
		const m = msgs[i];
		if (
			m &&
			m.role === 'user' &&
			m.text.trim() &&
			!m.uiOnly &&
			!m.queueState
		) {
			return {text: m.text, mediaRefs: [...(m.mediaRefs ?? [])]};
		}
	}
	return null;
}

/** 兼容只需要文本预览的调用方。 */
export function lastUserText(sessionId: string): string {
	return lastUserMessage(sessionId)?.text ?? '';
}
