import {parseMarkdownIntoBlocks} from 'streamdown';
import {TextLruCache, TEXT_CACHE_MAX_CHARS} from './textLruCache';
export {prepareStaticMarkdown, promoteDisplayMath, sanitizeMarkdown} from './markdownPrepare';

/**
 * markdownStaticCache.ts — settled Markdown 的跨实例解析缓存（P1-①）。
 *
 * 背景：滚动窗口 / 会话切换会让 settled 消息的 MarkdownView 反复重挂载。
 * 此前分块解析（parseMarkdownIntoBlocksFn）每实例重建，跨挂载零复用。
 *
 * 键为内容字符串本身；总字符量与条数同时设限。命中返回切片副本，缓存本体
 * 不暴露给调用方（库内部即使改写数组也不污染缓存）。
 *
 * 行为不变性：parseStaticBlocks(text) 的输出与直接调用
 * parseMarkdownIntoBlocks(text) 逐字节相同（确定性纯函数，仅做记忆化）；
 * prepareStaticMarkdown(text) 与 promoteDisplayMath(sanitizeMarkdown(text))
 * 相同。文本预处理独立在 markdownPrepare，避免把解析器带入启动依赖；
 * 此处保留 re-export 兼容，均有单测锁定。
 */

/** LRU 容量（内容条数）。settled 消息按引用命中，200 条覆盖近期活跃轮次。 */
const LRU_LIMIT = 200;

const blocksCache = new TextLruCache<string[]>(LRU_LIMIT, TEXT_CACHE_MAX_CHARS,
	blocks => blocks.reduce((total, block) => total + block.length, 0));

/** parseMarkdownIntoBlocks 的记忆化包装（输出逐字节相同）。 */
export function parseStaticBlocks(markdown: string): string[] {
	const hit = blocksCache.get(markdown);
	if (hit !== undefined) {
		return hit.slice();
	}
	const blocks = parseMarkdownIntoBlocks(markdown);
	blocksCache.set(markdown, blocks);
	return blocks.slice();
}
