import {describe, expect, it} from 'vitest';
import {
	computePaneViewportClamp,
	SIDEBAR_COMPACT_WIDTH_MAX,
	sidebarRenderedWidth,
} from './paneViewportClamp';

describe('pane viewport clamp', () => {
	it('uses the rendered compact sidebar width when yielding space to the workspace', () => {
		const sidebarWidth = sidebarRenderedWidth(420, true);
		expect(sidebarWidth).toBe(SIDEBAR_COMPACT_WIDTH_MAX);

		const result = computePaneViewportClamp(
			1000,
			{open: true, width: sidebarWidth},
			{open: true, width: 400},
		);

		expect(result).toEqual({sidebarEff: 280, workspaceEff: 380});
	});

	it('keeps the saved desktop sidebar width outside compact windows', () => {
		expect(sidebarRenderedWidth(420, false)).toBe(420);
	});
});
