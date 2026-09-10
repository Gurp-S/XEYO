import {confirmDialog} from '@/lib/inlineDialog';

/**
 * 删除会话前的二次确认。
 *
 * 为什么必须有：`removeSession` 是硬删——`tombstoneAndDeleteOnServer` 先标记本地墓碑
 * 再调服务端 DELETE，随后清掉 IDB 与全部 per-session 状态，**不可撤销**。
 * 而工作区删除（`removeSpace`）一直带 `confirmDialog({danger:true})`；
 * 两者危险级别相同却策略不对称，误点一次即永久丢失整段对话。
 *
 * 提示里给出「先归档」这条可逆替代路径：归档后的会话可用 `restoreSession` 恢复。
 */
export function confirmSessionDelete(title?: string): Promise<boolean> {
	return confirmDialog({
		title: `删除对话「${title?.trim() || '未命名'}」？`,
		body: '对话内容与本地记录会一并删除，无法恢复。如需保留，可先归档（归档后可随时恢复）。',
		confirmText: '删除',
		danger: true,
	});
}
