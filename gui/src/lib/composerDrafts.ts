/**
 * 按 session id 索引的 Composer 会话态（输入草稿 + 模式开关）。
 * 生命周期：写入 → 切换 session / 刷新 / 重启应用时保留（localStorage 同步落盘）
 * → 发送 / 删除 session 时清除。
 *
 * 持久化边界（2026-09-09）：
 * - 持久化：text、附件引用（文件 chip / 内联片段 / 已上传图片 mediaRef）、
 *   agentMode / permissionMode / multiAgent / reasoningEffort。
 * - 不持久化：未上传图片的 blob: previewUrl 与 File 句柄——刷新后必然失效，
 *   该类附件随刷新丢弃（发送链路 ensureMediaRefs 本就先上传后发送，见 Composer）。
 * - 配额：localStorage 单键 JSON；超限/损坏一律静默回退内存态（方向安全，
 *   最坏表现 = 退回旧行为「草稿仅内存」）。
 */

import {apiUrl} from '@/lib/apiBase';
import {normalizeAgentMode, type AgentMode} from '@/lib/agentMode';

export type PermissionMode = 'always' | 'risk' | 'never';

function normalizePermissionMode(v: unknown): PermissionMode {
	return v === 'always' || v === 'never' || v === 'risk' ? v : 'risk';
}

export type DraftFileAttachment = {
	kind: 'file';
	id: string;
	name: string;
	/** 工作区相对路径：整文件引用（chip 形式，不塞全文）。 */
	path?: string;
	/** 选区/小片段正文；与 path 二选一或并存（有 text 时发送内联片段）。 */
	text?: string;
};

export type DraftImageAttachment = {
	kind: 'image';
	id: string;
	name: string;
	previewUrl: string;
	mime: string;
	bytes: number;
	/** 页面内暂存的原始文件，仅用于尚未上传的图片；不写入持久层。 */
	file?: File;
	/** 后端上传成功后的不可变引用。 */
	mediaRef?: string;
};

export type DraftAttachment = DraftFileAttachment | DraftImageAttachment;

export type ComposerDraft = {
	text: string;
	attachments: DraftAttachment[];
	agentMode: AgentMode;
	permissionMode: PermissionMode;
	multiAgent: boolean;
	/** 会话输入框手动选的思考等级；空 = 该模型默认/会话级。 */
	reasoningEffort: string;
};

/** 持久化条目：仅存可跨刷新恢复的字段（图片丢 file/previewUrl，保留 mediaRef）。 */
type PersistedDraft = {
	text: string;
	attachments: PersistedAttachment[];
	agentMode: AgentMode;
	permissionMode: PermissionMode;
	multiAgent: boolean;
	reasoningEffort: string;
	/** 最后写入时间戳：配额逐出排序用。 */
	ts: number;
};

type PersistedAttachment =
	| {
			kind: 'file';
			id: string;
			name: string;
			path?: string;
			text?: string;
	  }
	| {
			kind: 'image';
			id: string;
			name: string;
			mediaRef: string;
			mime: string;
			bytes: number;
	  };

const STORAGE_KEY = 'xy:composerDrafts:v1';
/** 单会话草稿上限（文本 + 片段粗估字符数）；超限不持久化该会话，内存态不受影响。 */
const MAX_DRAFT_CHARS = 24_000;
/** 持久化条目数上限（防止 tombstone 会话无界累积）。 */
const MAX_DRAFTS = 64;
/** 单键总配额（粗估字符数）；超限按 ts 逐出最旧。 */
const MAX_TOTAL_CHARS = 192_000;

const PERSIST_DEBOUNCE_MS = 250;

const drafts = new Map<string, ComposerDraft>();

let loaded = false;
let persistTimer: ReturnType<typeof setTimeout> | null = null;

function storage(): Storage | null {
	try {
		if (typeof window === 'undefined' || !window.localStorage) {
			return null;
		}
		return window.localStorage;
	} catch {
		return null;
	}
}

/** 未上传图片不落盘；已上传图片丢 blob/句柄、保留 mediaRef。 */
function toPersistedAttachment(
	a: DraftAttachment,
): PersistedAttachment | null {
	if (a.kind === 'file') {
		return {kind: 'file', id: a.id, name: a.name, path: a.path, text: a.text};
	}
	return a.mediaRef
		? {
				kind: 'image',
				id: a.id,
				name: a.name,
				mediaRef: a.mediaRef,
				mime: a.mime,
				bytes: a.bytes,
			}
		: null;
}

function fromPersistedAttachment(
	a: PersistedAttachment,
): DraftAttachment | null {
	if (a.kind === 'file') {
		return {kind: 'file', id: a.id, name: a.name, path: a.path, text: a.text};
	}
	const digest = mediaRefDigest(a.mediaRef);
	if (!digest) {
		return null; // 畸形 mediaRef：宁可丢弃，不给输入框挂死链预览。
	}
	return {
		kind: 'image',
		id: a.id,
		name: a.name,
		// blob 预览地址已失效；重挂载后从后端只读端点回显（mediaUrl 同语义）。
		previewUrl: apiUrl(`/v1/media/${digest}`),
		mime: a.mime,
		bytes: a.bytes,
		mediaRef: a.mediaRef,
	};
}

/** xeyo-media://<64hex> → <64hex>；畸形引用返回空（调用方据以丢弃该附件）。 */
function mediaRefDigest(mediaRef: string): string {
	const match = /^xeyo-media:\/\/([0-9a-f]{64})$/i.exec((mediaRef || '').trim());
	if (!match) {
		return '';
	}
	return match[1].toLowerCase();
}

function sanitizePersisted(raw: unknown): PersistedDraft | null {
	if (!raw || typeof raw !== 'object') {
		return null;
	}
	const o = raw as Record<string, unknown>;
	if (typeof o.text !== 'string') {
		return null;
	}
	if (!Array.isArray(o.attachments)) {
		return null;
	}
	const attachments: PersistedAttachment[] = [];
	for (const item of o.attachments) {
		if (!item || typeof item !== 'object') {
			continue;
		}
		const a = item as Record<string, unknown>;
		if (a.kind === 'file') {
			if (typeof a.name !== 'string' || !a.name) {
				continue;
			}
			attachments.push({
				kind: 'file',
				id:
					typeof a.id === 'string' && a.id
						? a.id
						: `draft-file-${Math.random().toString(36).slice(2, 10)}`,
				name: a.name,
				path: typeof a.path === 'string' && a.path ? a.path : undefined,
				text: typeof a.text === 'string' ? a.text : undefined,
			});
		} else if (a.kind === 'image') {
			if (typeof a.mediaRef !== 'string' || !a.mediaRef) {
				continue; // 未上传图片不恢复（blob 已死）。
			}
			attachments.push({
				kind: 'image',
				id:
					typeof a.id === 'string' && a.id
						? a.id
						: `draft-img-${Math.random().toString(36).slice(2, 10)}`,
				name: typeof a.name === 'string' ? a.name : 'image',
				mediaRef: a.mediaRef,
				mime: typeof a.mime === 'string' ? a.mime : 'image/png',
				bytes: typeof a.bytes === 'number' ? a.bytes : 0,
			});
		}
	}
	return {
		text: o.text,
		attachments,
		agentMode: normalizeAgentMode(o.agentMode),
		permissionMode: normalizePermissionMode(o.permissionMode),
		multiAgent: o.multiAgent === true,
		reasoningEffort:
			typeof o.reasoningEffort === 'string' ? o.reasoningEffort : '',
		ts: typeof o.ts === 'number' && Number.isFinite(o.ts) ? o.ts : 0,
	};
}

function loadAll(): Map<string, PersistedDraft> {
	const out = new Map<string, PersistedDraft>();
	const ls = storage();
	if (!ls) {
		return out;
	}
	try {
		const raw = ls.getItem(STORAGE_KEY);
		if (!raw) {
			return out;
		}
		const parsed: unknown = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object') {
			return out;
		}
		for (const [id, item] of Object.entries(
			parsed as Record<string, unknown>,
		)) {
			const d = sanitizePersisted(item);
			if (d) {
				out.set(id, d);
			}
		}
	} catch {
		/* 损坏即丢弃：内存态继续可用 */
	}
	return out;
}

/** 粗估序列化字符数（JSON 转义后文本 ≈1.05 倍；附件按结构开销计）。 */
function serializeChars(d: PersistedDraft): number {
	return (
		Math.ceil(d.text.length * 1.05) +
		d.attachments.reduce(
			(n, a) => n + (a.kind === 'file' ? (a.text?.length ?? 0) + 120 : 200),
			0,
		) +
		120
	);
}

function writeAll(snapshot: Map<string, PersistedDraft>) {
	const ls = storage();
	if (!ls) {
		return;
	}
	// 配额裁剪：单会话超限先剔，条数超限与总配额超限按 ts 逐出最旧。
	let entries = [...snapshot.entries()].filter(
		([, d]) => serializeChars(d) <= MAX_DRAFT_CHARS,
	);
	entries.sort((a, b) => a[1].ts - b[1].ts);
	while (entries.length > MAX_DRAFTS) {
		entries.shift();
	}
	let total = entries.reduce((n, [, d]) => n + serializeChars(d), 0);
	while (entries.length > 0 && total > MAX_TOTAL_CHARS) {
		const dropped = entries.shift();
		if (dropped) {
			total -= serializeChars(dropped[1]);
		}
	}
	const obj: Record<string, PersistedDraft> = {};
	for (const [id, d] of entries) {
		obj[id] = d;
	}
	try {
		ls.setItem(STORAGE_KEY, JSON.stringify(obj));
	} catch {
		/* 写失败（配额/隐私模式）：静默回退内存态 */
	}
}

/** 立即把内存草稿落盘（pagehide / visibilitychange / 防抖触发）。 */
export function flushPersistDrafts(): void {
	if (persistTimer !== null) {
		clearTimeout(persistTimer);
		persistTimer = null;
	}
	if (!loaded) {
		return;
	}
	const snapshot = new Map<string, PersistedDraft>();
	const now = Date.now();
	for (const [id, d] of drafts) {
		snapshot.set(id, {
			text: d.text,
			attachments: d.attachments
				.map(toPersistedAttachment)
				.filter((a): a is PersistedAttachment => a !== null),
			agentMode: d.agentMode,
			permissionMode: d.permissionMode,
			multiAgent: d.multiAgent,
			reasoningEffort: d.reasoningEffort,
			ts: now,
		});
	}
	writeAll(snapshot);
}

function schedulePersist() {
	if (typeof window === 'undefined') {
		return;
	}
	if (persistTimer !== null) {
		clearTimeout(persistTimer);
	}
	persistTimer = setTimeout(() => {
		persistTimer = null;
		flushPersistDrafts();
	}, PERSIST_DEBOUNCE_MS);
}

if (typeof window !== 'undefined') {
	// 刷新/关闭前最后落盘一次（settingsStore 同款钩子）。
	window.addEventListener('pagehide', flushPersistDrafts);
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'hidden') {
			flushPersistDrafts();
		}
	});
}

function ensureLoaded() {
	if (loaded) {
		return;
	}
	loaded = true;
	const stored = loadAll();
	for (const [id, d] of stored) {
		const attachments: DraftAttachment[] = [];
		for (const a of d.attachments) {
			const restored = fromPersistedAttachment(a);
			if (restored) {
				attachments.push(restored);
			}
		}
		drafts.set(id, {
			text: d.text,
			attachments,
			agentMode: d.agentMode,
			permissionMode: d.permissionMode,
			multiAgent: d.multiAgent,
			reasoningEffort: d.reasoningEffort,
		});
	}
}

export function defaultComposerDraft(
	partial?: Partial<ComposerDraft>,
): ComposerDraft {
	return {
		text: partial?.text ?? '',
		attachments: partial?.attachments?.slice() ?? [],
		agentMode: normalizeAgentMode(partial?.agentMode ?? 'agent'),
		permissionMode: normalizePermissionMode(
			partial?.permissionMode ?? 'risk',
		),
		multiAgent: Boolean(partial?.multiAgent),
		reasoningEffort: partial?.reasoningEffort ?? '',
	};
}

export function getComposerDraft(sessionId: string): ComposerDraft | undefined {
	ensureLoaded();
	return drafts.get(sessionId);
}

export function setComposerDraft(
	sessionId: string,
	draft: Partial<ComposerDraft> &
		Pick<ComposerDraft, 'text' | 'attachments'>,
): void {
	ensureLoaded();
	const prev = drafts.get(sessionId);
	drafts.set(
		sessionId,
		defaultComposerDraft({
			...prev,
			...draft,
			attachments: draft.attachments.slice(),
		}),
	);
	schedulePersist();
}

/** 更新当前会话草稿中的模式字段（不改动 text/attachments）。 */
export function patchComposerDraftModes(
	sessionId: string,
	patch: Partial<
		Pick<
			ComposerDraft,
			'agentMode' | 'permissionMode' | 'multiAgent' | 'reasoningEffort'
		>
	>,
): void {
	ensureLoaded();
	const prev = drafts.get(sessionId) ?? defaultComposerDraft();
	drafts.set(
		sessionId,
		defaultComposerDraft({
			...prev,
			...patch,
			attachments: prev.attachments.slice(),
		}),
	);
	schedulePersist();
}

/** 删除草稿并 revoke 所有图片 object URL。 */
export function clearComposerDraft(sessionId: string): void {
	ensureLoaded();
	const prev = drafts.get(sessionId);
	if (prev) {
		revokeImages(prev.attachments);
		drafts.delete(sessionId);
		schedulePersist();
	}
}

/** 测试辅助 — 清空所有草稿（含持久层），不假设 session id。 */
export function resetComposerDraftsForTests(): void {
	if (persistTimer !== null) {
		clearTimeout(persistTimer);
		persistTimer = null;
	}
	for (const draft of drafts.values()) {
		revokeImages(draft.attachments);
	}
	drafts.clear();
	loaded = true;
	try {
		window.localStorage.removeItem(STORAGE_KEY);
	} catch {
		/* ignore */
	}
}

function revokeImages(attachments: DraftAttachment[]) {
	for (const a of attachments) {
		if (a.kind === 'image') {
			URL.revokeObjectURL(a.previewUrl);
		}
	}
}
