import {act, render, type RenderOptions} from '@testing-library/react';
import type {ReactNode} from 'react';
import {vi} from 'vitest';

/** Exercise the real lazy boundary and wait for its module before assertions. */
export async function renderDeferred(ui: ReactNode, options?: RenderOptions) {
	const view = render(ui, options);
	await act(async () => { await vi.dynamicImportSettled(); });
	return view;
}
