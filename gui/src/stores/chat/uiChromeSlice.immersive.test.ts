import {beforeEach, describe, expect, it, vi} from 'vitest';

const setOpen = vi.fn();
vi.mock('@/stores/workspaceStore', () => ({
	useWorkspaceStore: {
		getState: () => ({setOpen}),
	},
}));

const closeUsage = vi.fn();
vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: {
		getState: () => ({closeUsage}),
	},
}));

// 使用真实 chatStore（含 uiChromeSlice），验证 setImmersive 的布局副作用。
import {useChatStore} from '@/stores/chatStore';

describe('uiChromeSlice.immersive (P3-⑫)', () => {
	beforeEach(() => {
		setOpen.mockReset();
		closeUsage.mockReset();
		useChatStore.setState({immersive: false, sidebarOpen: true});
	});

	it('setImmersive(true) hides sidebar, workspace, usage and sets immersive', () => {
		useChatStore.getState().setImmersive(true);
		expect(useChatStore.getState().immersive).toBe(true);
		expect(useChatStore.getState().sidebarOpen).toBe(false);
		expect(setOpen).toHaveBeenCalledWith(false);
		expect(closeUsage).toHaveBeenCalled();
	});

	it('setImmersive(false) only clears the flag', () => {
		useChatStore.setState({immersive: true, sidebarOpen: false});
		useChatStore.getState().setImmersive(false);
		expect(useChatStore.getState().immersive).toBe(false);
		// 退出时不清 workspace/usage（避免误关）；关闭由用户手动恢复侧边栏。
		expect(setOpen).not.toHaveBeenCalledWith(false);
	});
});
