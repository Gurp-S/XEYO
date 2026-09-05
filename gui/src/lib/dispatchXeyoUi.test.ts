import {beforeEach, describe, expect, it, vi} from 'vitest';
import {
	dispatchXeyoUi,
	resetXeyoUiDispatchForTests,
} from '@/lib/dispatchXeyoUi';

const openPreview = vi.fn(async (_path: string) => undefined);
const openPanel = vi.fn((_panel: string) => undefined);
const setToolFlow = vi.fn((_show: boolean) => undefined);
const controlBrowser = vi.fn((_opts?: {url?: string; op?: string}) => undefined);

vi.mock('@/lib/openWorkspacePreview', () => ({
	openWorkspacePreview: (path: string) => openPreview(path),
	openWorkspacePanel: (panel: string) => openPanel(panel),
	setMapToolFlowVisible: (show: boolean) => setToolFlow(show),
	controlBrowserPreview: (opts?: {url?: string; op?: string}) =>
		controlBrowser(opts),
}));

vi.mock('@/lib/toast', () => ({
	toast: {success: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn()},
}));

describe('dispatchXeyoUi', () => {
	beforeEach(() => {
		resetXeyoUiDispatchForTests();
		openPreview.mockReset();
		openPanel.mockReset();
		setToolFlow.mockReset();
		controlBrowser.mockReset();
	});

	it('opens preview once per toolUseId', () => {
		dispatchXeyoUi(
			{action: 'open_preview', path: '/a.ts'},
			{toolUseId: 'tu1'},
		);
		dispatchXeyoUi(
			{action: 'open_preview', path: '/a.ts'},
			{toolUseId: 'tu1'},
		);
		expect(openPreview).toHaveBeenCalledTimes(1);
		expect(openPreview).toHaveBeenCalledWith('/a.ts');
	});

	it('opens panel', () => {
		dispatchXeyoUi({action: 'open_panel', panel: 'git'});
		expect(openPanel).toHaveBeenCalledWith('git');
	});

	it('toggles tool-flow map', () => {
		dispatchXeyoUi({action: 'show_tool_flow', show: true});
		expect(setToolFlow).toHaveBeenCalledWith(true);
		dispatchXeyoUi({action: 'show_tool_flow', show: false});
		expect(setToolFlow).toHaveBeenCalledWith(false);
	});

	it('controls browser preview', () => {
		dispatchXeyoUi({action: 'browser', url: 'http://localhost:5173'});
		expect(controlBrowser).toHaveBeenCalledWith({
			url: 'http://localhost:5173',
		});
		dispatchXeyoUi({action: 'browser', op: 'reload'});
		expect(controlBrowser).toHaveBeenCalledWith({op: 'reload'});
		dispatchXeyoUi({action: 'browser'});
		expect(controlBrowser).toHaveBeenCalledWith({});
	});

	it('ignores errors', () => {
		dispatchXeyoUi(
			{action: 'open_preview', path: '/a.ts'},
			{isError: true},
		);
		expect(openPreview).not.toHaveBeenCalled();
	});
});
