/**
 * 按 session id 索引的 Composer 会话态（输入草稿 + 模式开关）。
 * 生命周期：写入 → 切换 session 时保留 → 发送 / 删除 session / 退出应用时清除。
 * 永不持久化到磁盘 / IDB。
 */

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
	/** 页面内暂存的原始文件，仅用于尚未上传的图片；不写入 IDB。 */
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

const drafts = new Map<string, ComposerDraft>();

function revokeImages(attachments: DraftAttachment[]) {
	for (const a of attachments) {
		if (a.kind === 'image') {
			URL.revokeObjectURL(a.previewUrl);
		}
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
	return drafts.get(sessionId);
}

export function setComposerDraft(
	sessionId: string,
	draft: Partial<ComposerDraft> &
		Pick<ComposerDraft, 'text' | 'attachments'>,
): void {
	const prev = drafts.get(sessionId);
	drafts.set(
		sessionId,
		defaultComposerDraft({
			...prev,
			...draft,
			attachments: draft.attachments.slice(),
		}),
	);
}

/** 更新当前会话草稿中的模式字段（不改动 text/attachments）。 */
export function patchComposerDraftModes(
	sessionId: string,
	patch: Partial<
		Pick<ComposerDraft, 'agentMode' | 'permissionMode' | 'multiAgent'>
	>,
): void {
	const prev = drafts.get(sessionId) ?? defaultComposerDraft();
	drafts.set(
		sessionId,
		defaultComposerDraft({
			...prev,
			...patch,
			attachments: prev.attachments.slice(),
		}),
	);
}

/** 删除草稿并 revoke 所有图片 object URL。 */
export function clearComposerDraft(sessionId: string): void {
	const prev = drafts.get(sessionId);
	if (prev) {
		revokeImages(prev.attachments);
		drafts.delete(sessionId);
	}
}

/** 测试辅助 — 清空所有草稿，不假设 session id。 */
export function resetComposerDraftsForTests(): void {
	for (const draft of drafts.values()) {
		revokeImages(draft.attachments);
	}
	drafts.clear();
}
