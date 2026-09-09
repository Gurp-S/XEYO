import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

// 用 resetModules + 动态 import 模拟「页面刷新后模块重载」：
// 模块级 drafts Map 重建，从 localStorage 恢复持久化条目。
async function loadFresh() {
	vi.resetModules();
	return await import('@/lib/composerDrafts');
}

type DraftsModule = typeof import('@/lib/composerDrafts');

let mod: DraftsModule;

beforeEach(async () => {
	window.localStorage.clear();
	mod = await loadFresh();
});

afterEach(() => {
	try {
		window.localStorage.clear();
	} catch {
		/* ignore */
	}
});

describe('composerDrafts 持久化（刷新恢复）', () => {
	it('text + 模式字段经 flush 落盘，模块重载后同会话可恢复', () => {
		mod.setComposerDraft('sess_a', {
			text: '你好，帮我写个脚本',
			attachments: [],
			agentMode: 'agent',
			permissionMode: 'never',
			multiAgent: true,
			reasoningEffort: 'high',
		});
		mod.flushPersistDrafts();
		expect(window.localStorage.getItem('xy:composerDrafts:v1')).toContain(
			'你好，帮我写个脚本',
		);
	});

	it('模块重载（模拟刷新）后按 session 恢复草稿与模式', async () => {
		mod.setComposerDraft('sess_a', {
			text: '第一条',
			attachments: [],
			permissionMode: 'never',
		});
		mod.setComposerDraft('sess_b', {
			text: '第二条',
			attachments: [],
			permissionMode: 'always',
		});
		mod.flushPersistDrafts();

		// 模拟刷新：全新模块实例从 localStorage 恢复
		const reloaded = await loadFresh();
		expect(reloaded.getComposerDraft('sess_a')?.text).toBe('第一条');
		expect(reloaded.getComposerDraft('sess_a')?.permissionMode).toBe('never');
		expect(reloaded.getComposerDraft('sess_b')?.text).toBe('第二条');
		expect(reloaded.getComposerDraft('sess_b')?.permissionMode).toBe('always');
		// 会话隔离：互不串
		expect(reloaded.getComposerDraft('sess_a')?.permissionMode).not.toBe('always');
	});

	it('file 附件（path/text）跨刷新保留', async () => {
		mod.setComposerDraft('sess_a', {
			text: '',
			attachments: [
				{kind: 'file', id: 'f1', name: 'a.py', path: 'src/a.py'},
				{kind: 'file', id: 'f2', name: 'sel', text: 'for x in y:'},
			],
		});
		mod.flushPersistDrafts();
		const reloaded = await loadFresh();
		const atts = reloaded.getComposerDraft('sess_a')?.attachments ?? [];
		expect(atts).toHaveLength(2);
		expect(atts[0]).toMatchObject({kind: 'file', path: 'src/a.py'});
		expect(atts[1]).toMatchObject({kind: 'file', text: 'for x in y:'});
	});

	it('未上传图片（无 mediaRef）不持久化；已上传（mediaRef）跨刷新恢复为只读回显 URL', async () => {
		mod.setComposerDraft('sess_a', {
			text: '',
			attachments: [
				{
					kind: 'image',
					id: 'img1',
					name: 'shot.png',
					previewUrl: 'blob:http://x/1',
					mime: 'image/png',
					bytes: 10,
					file: {} as File, // 未上传
				},
				{
					kind: 'image',
					id: 'img2',
					name: 'up.png',
					previewUrl: 'blob:http://x/2',
					mime: 'image/png',
					bytes: 20,
					mediaRef: 'xeyo-media://' + 'a'.repeat(64),
				},
			],
		});
		mod.flushPersistDrafts();
		const reloaded = await loadFresh();
		const atts = reloaded.getComposerDraft('sess_a')?.attachments ?? [];
		expect(atts).toHaveLength(1);
		expect(atts[0]).toMatchObject({kind: 'image', mediaRef: 'xeyo-media://' + 'a'.repeat(64)});
		// 恢复后 preview 指向后端只读回显端点，而不是已失效的 blob
		expect(atts[0].kind === 'image' && atts[0].previewUrl).toContain('/v1/media/');
	});

	it('损坏 / 畸形持久化条目被静默丢弃，不影响其它会话恢复', async () => {
		window.localStorage.setItem(
			'xy:composerDrafts:v1',
			JSON.stringify({
				sess_good: {text: 'ok', attachments: [], agentMode: 'agent', permissionMode: 'risk', multiAgent: false, reasoningEffort: '', ts: 1},
				sess_bad_text: {attachments: [], ts: 2}, // 缺 text
				sess_bad_media: {
					text: 'x',
					attachments: [{kind: 'image', id: 'm', name: 'm', mediaRef: 'not-a-media-ref'}],
					agentMode: 'agent', permissionMode: 'risk', multiAgent: false, reasoningEffort: '', ts: 3,
				},
			}),
		);
		const reloaded = await loadFresh();
		expect(reloaded.getComposerDraft('sess_good')?.text).toBe('ok');
		// 缺 text → 整条丢弃
		expect(reloaded.getComposerDraft('sess_bad_text')).toBeUndefined();
		// 畸形 mediaRef 附件被丢（条目保留，附件为空）
		expect(reloaded.getComposerDraft('sess_bad_media')?.attachments).toHaveLength(0);
	});

	it('超限（>MAX_DRAFT_CHARS）会话不落盘，内存态不受影响', async () => {
		mod.setComposerDraft('sess_a', {
			text: 'x'.repeat(25_000),
			attachments: [],
		});
		mod.flushPersistDrafts();
		// 内存态仍在
		expect(mod.getComposerDraft('sess_a')?.text).toHaveLength(25_000);
		const reloaded = await loadFresh();
		expect(reloaded.getComposerDraft('sess_a')).toBeUndefined();
	});
});
