import {confirmDialog} from '@/lib/inlineDialog';

/**
 * 删除会话前的二次确认。
 *
 * 为什么必须有：`removeSession` 是硬删——`tombstoneAndDeleteOnServer` 先标记本地墓碑
 * 再调服务端 DELETE，随后清掉 IDB 与全部 per-session 状态，**不可撤销**。
 * 作为对照，工作区侧的「移除工作区」是可逆操作（仅从侧栏隐藏，重开文件夹即恢复），
 * 故它不再套危险样式——两者危险级别不同，策略本就不该对称。
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
