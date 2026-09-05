/**
 * slash 弹层键盘仲裁 —— 纯函数核（参考 DeepSeek Harness ui-input-trigger 的
 * combobox 仲裁语义：焦点始终留在编辑器表面，弹层开着时 ↑↓/Tab/Enter/Esc
 * 被拦截；IME 组词期间一律放行；无高亮时 Enter 放行提交）。
 *
 * 高亮索引是「扁平列表」下标：渲染顺序 = 技能组在前、命令组在后，
 * 与 Composer 弹层的行序一致。hover 与键盘共用同一高亮（后到者胜）。
 */

export type SlashMenuKey = 'up' | 'down' | 'enter' | 'tab' | 'escape';

export type SlashMenuArbitration =
	| {type: 'pass'}
	/** 移动高亮；dir 相对当前（-1 上一项 / 1 下一项），环形滚动 */
	| {type: 'move'; dir: -1 | 1; next: number}
	/** 选中扁平列表第 index 项（弹层随之关闭） */
	| {type: 'pick'; index: number}
	/** 关闭弹层（Esc） */
	| {type: 'close'};

export type SlashMenuArbitrateInput = {
	key: SlashMenuKey;
	/** IME 组词中：一切按键放行给编辑器 */
	composing: boolean;
	/** 当前高亮（null = 无高亮） */
	highlight: number | null;
	/** 扁平候选项总数 */
	count: number;
};

export function arbitrateSlashMenuKey(input: SlashMenuArbitrateInput): SlashMenuArbitration {
	const {key, composing, highlight, count} = input;
	if (composing) {
		return {type: 'pass'};
	}
	switch (key) {
		case 'escape':
			return {type: 'close'};
		case 'up':
		case 'down': {
			if (count <= 0) {
				return {type: 'pass'};
			}
			const dir = key === 'up' ? -1 : 1;
			const base = highlight ?? (dir === 1 ? -1 : 0);
			const next = (((base + dir) % count) + count) % count;
			return {type: 'move', dir, next};
		}
		case 'enter':
		case 'tab':
			// 无高亮 → 放行（Enter 走提交 / Tab 走焦点遍历）；
			// 有高亮 → 选中该行并关闭弹层。
			if (highlight === null || highlight < 0 || highlight >= count) {
				return {type: 'pass'};
			}
			return {type: 'pick', index: highlight};
		default:
			return {type: 'pass'};
	}
}
