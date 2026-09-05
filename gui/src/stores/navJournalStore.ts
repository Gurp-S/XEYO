import {create} from 'zustand';

/**
 * 全局导航日志（浏览器式 上一个/下一个界面）。
 *
 * 「界面」= 路由（含 search）+ 用量面板开合。多 Agent 子视图是会话内存态
 * （chatStore.agentViewStack），不进此栈 —— 切回该会话时恢复其自身记忆。
 *
 * 同步算法（record）：不区分 PUSH/POP 事件源，仅按内容就近匹配：
 *   - 与当前条目相同            → 忽略
 *   - 与上一条目相同            → 指针后移（后退）
 *   - 与下一条目相同            → 指针前移（前进）
 *   - 其余                      → 截断 forward 分支并入栈（新访问）
 * 这样无论导航来自链接点击、代码 redirect、浏览器按钮还是本组件箭头，
 * 栈都能保持一致的浏览器语义。
 */
export type NavEntry = {path: string; usageOpen: boolean};

const MAX_ENTRIES = 200;

type NavJournalState = {
	entries: NavEntry[];
	index: number;
	/** 路由/界面状态变化时由 NavJournalSync 调用；幂等。 */
	record: (entry: NavEntry) => void;
	/** 返回上一个界面（不出栈；导航提交后经 record 自然移动指针）。 */
	peekBack: () => NavEntry | null;
	/** 返回下一个界面。 */
	peekForward: () => NavEntry | null;
};

function sameEntry(a: NavEntry | undefined, b: NavEntry): boolean {
	return Boolean(a && a.path === b.path && a.usageOpen === b.usageOpen);
}

export const useNavJournalStore = create<NavJournalState>((set, get) => ({
	entries: [],
	index: -1,

	record(entry) {
		set(s => {
			const {entries, index} = s;
			if (sameEntry(entries[index], entry)) {
				return {};
			}
			if (sameEntry(entries[index - 1], entry)) {
				return {index: index - 1};
			}
			if (sameEntry(entries[index + 1], entry)) {
				return {index: index + 1};
			}
			let nextEntries = [...entries.slice(0, index + 1), entry];
			let nextIndex = nextEntries.length - 1;
			if (nextEntries.length > MAX_ENTRIES) {
				const overflow = nextEntries.length - MAX_ENTRIES;
				nextEntries = nextEntries.slice(overflow);
				nextIndex -= overflow;
			}
			return {entries: nextEntries, index: nextIndex};
		});
	},

	peekBack() {
		const {entries, index} = get();
		return index > 0 ? (entries[index - 1] ?? null) : null;
	},

	peekForward() {
		const {entries, index} = get();
		return index < entries.length - 1 ? (entries[index + 1] ?? null) : null;
	},
}));
