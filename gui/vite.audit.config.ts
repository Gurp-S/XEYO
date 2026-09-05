/**
 * vite.audit.config.ts — 审计专用 dev 配置（端口 5175）。
 *
 * 与 vite.config.ts 的差异：
 * - cacheDir 指到 `.tmp/vite-deps-audit`：改主 config 触发依赖重优化时要清空
 *   node_modules/.vite/deps（2000+ 文件），沙箱删除保护会拦死启动；独立缓存目录
 *   从零构建，不碰主缓存。
 * - 保留主 config 的 watch.ignored（测试产物写入不触发 page reload——
 *   2026-09-05 审计白屏的根因）。
 * 用法：`npx vite --config vite.audit.config.ts --port 5175`
 */
import {mergeConfig, type UserConfig} from 'vite';
import baseConfig from './vite.config';

const resolved = baseConfig({command: 'serve', mode: 'development'}) as UserConfig;

export default mergeConfig(
	{
		cacheDir: 'node_modules/.vite-audit-deps',
		// 预声明 highlight worker 的全部 prism 依赖：避免运行中「new dependencies
		// optimized → 整页 reload」打断审计（2026-09-05 C 段/探针失败根因）。
		optimizeDeps: {
			include: [
				'prismjs',
				'prismjs/components/prism-clike',
				'prismjs/components/prism-markup',
				'prismjs/components/prism-css',
				'prismjs/components/prism-javascript',
				'prismjs/components/prism-typescript',
				'prismjs/components/prism-jsx',
				'prismjs/components/prism-tsx',
				'prismjs/components/prism-python',
				'prismjs/components/prism-bash',
				'prismjs/components/prism-json',
				'prismjs/components/prism-yaml',
				'prismjs/components/prism-markdown',
				'prismjs/components/prism-go',
				'prismjs/components/prism-rust',
				'prismjs/components/prism-java',
				'prismjs/components/prism-c',
				'prismjs/components/prism-cpp',
				'prismjs/components/prism-csharp',
				'prismjs/components/prism-sql',
				'prismjs/components/prism-ruby',
				'prismjs/components/prism-kotlin',
				'prismjs/components/prism-docker',
			],
		},
	},
	resolved,
);
