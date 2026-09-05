import {defineConfig, type Plugin} from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';

const host = process.env.TAURI_DEV_HOST;
const shipContextIsland = process.env.VITE_XY_CONTEXT_ISLAND === '1';

/**
 * 解析后端实际监听端口，供 Vite 代理与前端（apiBase）使用。
 * 优先级：显式 VITE_XEYO_HTTP_PORT > 后端落盘端口文件(仅 dev) > XEYO_HTTP_PORT > 8000。
 * T30：端口文件升级为 JSON {port, pid, started_at, engine_version}——兼容旧纯数字。
 * 生产构建不读端口文件，避免陈旧 dev 端口被烤进发布包。
 */
function readPortFileValue(file: string): number | null {
	try {
		const raw = fs.readFileSync(file, 'utf-8').trim();
		if (!raw) return null;
		if (raw.startsWith('{')) {
			const data = JSON.parse(raw) as {port?: unknown};
			return typeof data.port === 'number' && data.port > 0 ? data.port : null;
		}
		return Number(raw) || null;
	} catch {
		/* 后端尚未启动/无端口文件：回落到配置端口 */
		return null;
	}
}

function resolveBackendPort(command: 'build' | 'serve' | string): number {
	if (process.env.VITE_XEYO_HTTP_PORT) {
		return Number(process.env.VITE_XEYO_HTTP_PORT);
	}
	if (command !== 'build') {
		const portFile =
			process.env.XEYO_PORT_FILE ||
			path.resolve(__dirname, '..', '.xeyo', 'backend_port');
		const fromFile = readPortFileValue(portFile);
		if (fromFile != null) {
			return fromFile;
		}
	}
	return Number(process.env.XEYO_HTTP_PORT || 8000);
}

/**
 * T29/T30：dev 代理每次请求重读端口文件——后端迁移端口后代理自动跟随，
 * 不再钉死在 Vite 启动那一刻解析的 target。
 */
function liveBackendPort(fallback: number): number {
	// 只信端口文件：VITE_XEYO_HTTP_PORT 是配置期注入的启动值，会掩盖迁移
	const portFile =
		process.env.XEYO_PORT_FILE ||
		path.resolve(__dirname, '..', '.xeyo', 'backend_port');
	return readPortFileValue(portFile) ?? fallback;
}

function backendFollowProxy(): Plugin {
	return {
		name: 'xeyo-backend-follow-proxy',
		apply: 'serve',
		configureServer(server) {
			const startupPort = resolveBackendPort('serve');
			server.middlewares.use((req, res, next) => {
				const url = req.url ?? '';
				if (!/^\/(?:v1|api|health)(?:\/|\?|$)/.test(url)) {
					next();
					return;
				}
				const port = liveBackendPort(startupPort);
				const upstream = http.request(
					{
						host: '127.0.0.1',
						port,
						method: req.method,
						path: url,
						headers: {...req.headers, host: `127.0.0.1:${port}`},
					},
					upres => {
						res.writeHead(upres.statusCode ?? 502, upres.headers);
						upres.pipe(res);
					},
				);
				upstream.on('error', () => {
					if (!res.headersSent) {
						res.writeHead(502, {'content-type': 'application/json'});
					}
					res.end(
						JSON.stringify({
							error: {
								message: `backend not reachable on 127.0.0.1:${port}`,
								type: 'backend_unreachable',
							},
						}),
					);
				});
				req.pipe(upstream);
			});
		},
	};
}

/** Drop heavy optional public assets from production dist (island gated off). */
function omitDeferredPublicAssets(): Plugin {
	const omitUnlessIsland = ['context-island/character/character.svg'];
	const alwaysOmit = [
		'context-pasture-design.png',
		'context-pasture-design-sheet.png',
		'context-pasture-composite.png',
		'pasture-scene-1.png',
		'pasture-scene-2.png',
		'pasture-scene-3.png',
		'pasture-scene-4.png',
		'pasture-scene-5.png',
	];
	return {
		name: 'omit-deferred-public-assets',
		closeBundle() {
			const outDir = path.resolve(__dirname, 'dist');
			const targets = [
				...alwaysOmit,
				...(shipContextIsland ? [] : omitUnlessIsland),
			];
			for (const rel of targets) {
				const file = path.join(outDir, rel);
				try {
					fs.unlinkSync(file);
				} catch {
					/* already absent */
				}
			}
		},
	};
}

export default defineConfig(({command}) => {
	// 给前端（apiBase）暴露实际后端端口；Vite 会把 VITE_ 前缀的 process.env 变量注入 import.meta.env
	const backendPort = resolveBackendPort(command);
	process.env.VITE_XEYO_HTTP_PORT = String(backendPort);

	return {
	plugins: [react(), tailwindcss(), omitDeferredPublicAssets(), backendFollowProxy()],
	resolve: {
		alias: {
			'@': path.resolve(__dirname, './src'),
		},
	},
	test: {
		environment: 'jsdom',
		globals: true,
		setupFiles: ['./src/test/setup.ts'],
		include: ['src/**/*.{test,spec}.{ts,tsx}'],
	},
	clearScreen: false,
	server: {
		port: 5173,
		// 端口被占用时自动往后找空闲端口（strictPort: true 会直接退出）
		strictPort: false,
		host: host || false,
		watch: {
			// 测试产物与 e2e 脚本不是前端源码：写它们不该触发 page reload
			// （2026-09-05 审计：ui-audit 运行时写截图 → vite 全页重载 → 误判白屏）。
			ignored: [
				'**/e2e/**',
				'**/test-results*/**',
				'**/ui-audit-report/**',
				'**/bench-results/**',
			],
		},
		hmr: host
			? {
					protocol: 'ws',
					host,
					port: 1421,
				}
			: undefined,
		// T30：/v1、/api、/health 由 backendFollowProxy 插件按端口文件动态转发。
		proxy: {},
	},
	envPrefix: ['VITE_', 'TAURI_'],
	build: {
		target: process.env.TAURI_ENV_PLATFORM === 'windows' ? 'chrome105' : 'safari13',
		minify: !process.env.TAURI_ENV_DEBUG ? 'esbuild' : false,
		sourcemap: !!process.env.TAURI_ENV_DEBUG,
		rollupOptions: {
			input: {
				main: path.resolve(__dirname, 'index.html'),
				pet: path.resolve(__dirname, 'pet.html'),
			},
			output: {
				manualChunks(id) {
					if (!id.includes('node_modules')) {
						return;
					}
					if (/[\\/]node_modules[\\/](?:@mermaid-js|mermaid)[\\/]/.test(id)) {
						return 'mermaid';
					}
					if (
						/[\\/]node_modules[\\/](?:@[^\\/]+[\\/])?katex[\\/]/.test(id) ||
						/[\\/]node_modules[\\/]remark-math[\\/]/.test(id) ||
						/[\\/]node_modules[\\/]rehype-katex[\\/]/.test(id)
					) {
						return 'katex';
					}
					if (
						/[\\/]node_modules[\\/]react-syntax-highlighter[\\/]/.test(id) ||
						/[\\/]node_modules[\\/]prismjs[\\/]/.test(id)
					) {
						return 'prism';
					}
				},
			},
		},
	},
	};
});
