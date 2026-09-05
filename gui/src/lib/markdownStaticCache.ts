import {parseMarkdownIntoBlocks} from 'streamdown';

/**
 * markdownStaticCache.ts — settled Markdown 的跨实例解析缓存（P1-①）。
 *
 * 背景：滚动窗口 / 会话切换会让 settled 消息的 MarkdownView 反复重挂载。
 * 此前分块解析（parseMarkdownIntoBlocksFn）每实例重建，跨挂载零复用。
 *
 * 键为内容字符串本身：同一消息对象重挂载时 content 引用不变，
 * Map 命中走引用相等快路径，O(1)。命中返回切片副本，缓存本体
 * 不暴露给调用方（库内部即使改写数组也不污染缓存）。
 *
 * 行为不变性：parseStaticBlocks(text) 的输出与直接调用
 * parseMarkdownIntoBlocks(text) 逐字节相同（确定性纯函数，仅做记忆化）；
 * prepareStaticMarkdown(text) 与 promoteDisplayMath(sanitizeMarkdown(text))
 * 相同。sanitizeMarkdown / promoteDisplayMath 的规范实现自此移入本模块
 * （MarkdownView re-export 兼容），逻辑逐字保留，均有单测锁定。
 */

/** LRU 容量（内容条数）。settled 消息按引用命中，200 条覆盖近期活跃轮次。 */
const LRU_LIMIT = 200;

function lruGet<T>(cache: Map<string, T>, key: string): T | undefined {
	const hit = cache.get(key);
	if (hit === undefined) {
		return undefined;
	}
	// 刷新 LRU 位置。
	cache.delete(key);
	cache.set(key, hit);
	return hit;
}

function lruSet<T>(cache: Map<string, T>, key: string, value: T): void {
	cache.set(key, value);
	while (cache.size > LRU_LIMIT) {
		const oldest = cache.keys().next().value;
		if (oldest === undefined) {
			return;
		}
		cache.delete(oldest);
	}
}

// ---------------------------------------------------------------------------
// 规范实现（自 MarkdownView 移入，逻辑逐字保留）
// ---------------------------------------------------------------------------

/** 去除可能破坏布局 / 高亮器的控制字符；保留 tab/换行。 */
export function sanitizeMarkdown(content: string): string {
	if (!content) {
		return '';
	}
	return content.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '');
}

/** 单行 `$$...$$` 升为块级，math 插件才能走 display。 */
export function promoteDisplayMath(content: string): string {
	if (!content.includes('$$')) {
		return content;
	}
	return content.replace(
		/^[ \t]*\$\$([^$\n][^]*?)\$\$[ \t]*$/gm,
		(_m, inner: string) => `$$\n${String(inner).trim()}\n$$`,
	);
}

// ---------------------------------------------------------------------------
// 记忆化包装
// ---------------------------------------------------------------------------

const blocksCache = new Map<string, string[]>();

/** parseMarkdownIntoBlocks 的记忆化包装（输出逐字节相同）。 */
export function parseStaticBlocks(markdown: string): string[] {
	const hit = lruGet(blocksCache, markdown);
	if (hit !== undefined) {
		return hit.slice();
	}
	const blocks = parseMarkdownIntoBlocks(markdown);
	lruSet(blocksCache, markdown, blocks);
	return blocks.slice();
}

const prepareCache = new Map<string, string>();

/** static 预处理（sanitize + promote）的记忆化包装。 */
export function prepareStaticMarkdown(markdown: string): string {
	const hit = lruGet(prepareCache, markdown);
	if (hit !== undefined) {
		return hit;
	}
	const safe = promoteDisplayMath(sanitizeMarkdown(markdown));
	lruSet(prepareCache, markdown, safe);
	return safe;
}
