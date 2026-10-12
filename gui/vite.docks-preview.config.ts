/**
 * vite.docks-preview.config.ts — 队列 / goal 条带样式预览页（静态，无 JS 应用）。
 *
 * 存在的理由：排队 dock 与 goal 条带的样式分散在
 *   src/styles/dock-panels.css（.xy-queue-*、.xy-panel-ask）+ tokens.css + Tailwind 工具类，
 * 只读源码看不出"长什么样"。本配置把 docks-preview.html 里照抄的真实 class 结构
 * 过一遍**真实的 Tailwind/ Vite 管线**，产出一个可双击打开的静态页。
 *
 * 用法：
 *   cd gui && npx vite build --config vite.docks-preview.config.ts
 *   → .tmp/docks-preview/docks-preview.html（双击即可，CSS 走相对路径）
 *
 * 与主配置的区别：不引入 react/后端代理/产物裁剪插件，只留 tailwindcss，
 * 避免构建整个应用、也避免误删 gui/dist 下的既有产物。
 */
import {defineConfig, type Plugin} from 'vite';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

/**
 * Vite 会给 <link rel=stylesheet> 加 crossorigin —— 在 file:// 下这条属性把
 * 同目录 CSS 变成 CORS 请求并被浏览器拦掉（ERR_FAILED，页面全裸）。
 * 本页要能双击打开，所以去掉它。
 */
function stripCrossorigin(): Plugin {
	return {
		name: 'strip-crossorigin',
		transformIndexHtml: {
			order: 'post',
			handler: html => html.replace(/ crossorigin/g, ''),
		},
	};
}

export default defineConfig({
	root: __dirname,
	base: './',
	// 样式页不引用 public/ 下任何资源（src 的 CSS 里没有 url()），
	// 关掉拷贝免得每份产物拖一整套壁纸/桌宠图。
	publicDir: false,
	plugins: [tailwindcss(), stripCrossorigin()],
	build: {
		outDir: '.tmp/docks-preview',
		emptyOutDir: true,
		sourcemap: false,
		rollupOptions: {
			input: {
				docksPreview: path.resolve(__dirname, 'docks-preview.html'),
			},
		},
	},
});
