import '@testing-library/jest-dom/vitest';
import {vi} from 'vitest';

/** 同步 flush rAF，以便测试流式合并。 */
vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
	cb(0);
	return 1;
});
vi.stubGlobal('cancelAnimationFrame', () => {});

vi.mock('@/stores/settingsStore', () => {
	const state = {
		theme: 'graphite' as const,
		provider: 'deepseek' as const,
		model: 'deepseek-v4-flash',
		apiKey: 'test-key',
		baseUrl: '',
		bgImage: '',
		bgOpacity: 40,
		bgBlur: 0,
		sidebarWidth: 260,
		previewWidth: 360,
		explorerWidth: 248,
		smoothness: true,
		remoteChannel: 'ilink' as const,
		hydrated: true,
		thinking: 'disabled' as const,
		reasoningEffort: '' as const,
		hydrate: vi.fn(),
		hydrateAsync: vi.fn(async () => undefined),
		update: vi.fn((patch: Record<string, unknown>) => {
			Object.assign(state, patch);
		}),
		profiles: [] as {
			id: string;
			provider: string;
			model: string;
			apiKey: string;
			baseUrl: string;
		}[],
		activeProfileId: '',
		selectProfile: vi.fn(),
		addProfile: vi.fn(),
		removeProfile: vi.fn(),
		openSettings: vi.fn(),
		closeSettings: vi.fn(),
		settingsModalOpen: false,
		resolvedBaseUrl: () => 'https://api.deepseek.com/v1',
	};
	const useSettingsStore = (
		selector?: (s: typeof state) => unknown,
	) => (selector ? selector(state) : state);
	useSettingsStore.getState = () => state;
	return {
		useSettingsStore,
		COMPOSER_MODEL_OPTIONS: [],
		MODEL_OPTIONS: [],
		REASONING_EFFORTS: [
			'none',
			'minimal',
			'low',
			'medium',
			'high',
			'xhigh',
			'max',
			'ultra',
		],
		PROVIDER_DEFAULT_URL: {
			deepseek: 'https://api.deepseek.com/v1',
			openai: 'https://api.openai.com/v1',
		},
		PROVIDER_LABEL: {deepseek: 'DeepSeek', openai: 'OpenAI'},
		keyFingerprint: (k: string) => (k ? '…test' : ''),
		profileModelIds: (p: {
			model?: string;
			models?: {id: string}[];
		}) =>
			p.models?.length
				? p.models.map(m => m.id).filter(Boolean)
				: p.model
					? [p.model]
					: [],
		SIDEBAR_WIDTH_MIN: 180,
		SIDEBAR_WIDTH_MAX: 420,
		PANE_WIDTH_MIN: 180,
		PANE_WIDTH_MAX: 420,
		applyDocumentTheme: vi.fn(),
		applyDocumentSmoothness: vi.fn(),
		isSmoothnessOn: (v?: unknown) => v !== false,
		normalizeRemoteChannel: (v: unknown) =>
			v === 'filehelper' ? 'filehelper' : 'ilink',
		// 复刻 settingsStore.isProviderId 的真实语义：deepseek/openai 恒真；
		// local/fake 受 LOCAL-TEST gate 管理（localStorage XEYO_ENABLE_LOCAL_TEST=1）。
		isProviderId: (v: unknown) => {
			if (v === 'deepseek' || v === 'openai') {
				return true;
			}
			return (
				(v === 'local' || v === 'fake') &&
				typeof window !== 'undefined' &&
				window.localStorage.getItem('XEYO_ENABLE_LOCAL_TEST') === '1'
			);
		},
	};
});
