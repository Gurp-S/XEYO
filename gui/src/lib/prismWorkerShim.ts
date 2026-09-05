/**
 * prismWorkerShim.ts — 伪装最小 document，让 prismjs 在 Worker 里走"主线程分支"。
 *
 * 根因（2026-09-05 GUI 审计 P1）：prismjs 在 Worker 环境（无 document）会注册全局
 * `message` 监听并 `JSON.parse(evt.data)`（其自带的 worker 自动高亮协议）。
 * 本项目 highlight worker 收发的是**对象消息**（HighlightRequest/Response）→
 * 每条高亮请求都抛一次未捕获的 `SyntaxError: "[object Object]" is not valid JSON`。
 *
 * 修法：在 prismjs 求值**之前**提供最小 document 伪装——readyState 恒为 'loading'，
 * 事件监听为 noop，prism 走主线程分支、DOMContentLoaded 永不触发、自动高亮永不执行，
 * 也不再注册 worker 消息监听。Worker 内只用 `Prism.highlight`（纯字符串运算），
 * 不受该伪装影响。
 *
 * 使用约束：必须作为 highlightWorker.ts 的**第一个** import（ESM 按声明序求值，
 * 保证本模块先于 prismjs 执行）。
 */

const w = self as unknown as Record<string, unknown>;
if (!w.document) {
	w.document = {
		readyState: 'loading',
		addEventListener: () => {},
		removeEventListener: () => {},
		currentScript: null,
		scripts: [],
		querySelectorAll: () => [],
		createElement: () => ({
			style: {},
			setAttribute() {},
			remove() {},
		}),
		head: {appendChild() {}, removeChild() {}},
		body: {appendChild() {}, removeChild() {}},
	};
}
// prism 末尾的 autoloader/fileHighlight 插件块会访问 `Element.prototype.matches`；
// worker 里只调用纯函数 Prism.highlight，这些插件永不触发，最小构造即可。
if (!w.Element) {
	w.Element = class Element {};
}
