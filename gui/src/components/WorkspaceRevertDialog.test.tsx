import {act, cleanup, render, screen} from '@testing-library/react';
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest';
import type {RewindV3DialogState} from '@/stores/rewindV3Store';

const {useRewindV3Store} = await import('@/stores/rewindV3Store');
const {RewindV3Dialog} = await import('@/components/WorkspaceRevertDialog');

const SESSION_ID = 'rewind-dialog-remount';

const RUNNING_STATE: RewindV3DialogState = {
	phase: 'running',
	targetMessageId: 'message-1',
	editedText: 'edited prompt',
	action: 'continue',
	checkpointState: 'none',
	checkpointId: null,
	rewindId: 'rewind-1',
	pillRewindId: null,
	summary: null,
	error: null,
	attemptId: 'attempt-1',
	settled: false,
	suffixBackup: null,
	recovery: false,
	resendPending: false,
	checkpointAnchor: null,
};

const DONE_STATE: RewindV3DialogState = {
	...RUNNING_STATE,
	phase: 'done',
	settled: true,
	summary: '回溯已完成',
};

beforeAll(() => {
	HTMLDialogElement.prototype.showModal = function showModal() {
		this.setAttribute('open', '');
	};
	HTMLDialogElement.prototype.close = function close() {
		this.removeAttribute('open');
	};
});

beforeEach(() => {
	useRewindV3Store.setState({
		bySession: {[SESSION_ID]: RUNNING_STATE},
		pillsBySession: {},
	});
});

afterEach(() => {
	cleanup();
	useRewindV3Store.setState({bySession: {}, pillsBySession: {}});
});

describe('RewindV3Dialog completion lifecycle', () => {
	it('shows same-lifetime completion after the dialog host remounts', () => {
		const firstMount = render(<RewindV3Dialog sessionId={SESSION_ID} />);
		expect(firstMount.container.querySelector('dialog')?.open).toBe(true);
		firstMount.unmount();

		act(() => {
			useRewindV3Store.setState({
				bySession: {[SESSION_ID]: DONE_STATE},
			});
		});

		const secondMount = render(<RewindV3Dialog sessionId={SESSION_ID} />);
		expect(secondMount.container.querySelector('dialog')?.open).toBe(true);
		expect(screen.getByRole('heading', {name: '回溯完成'})).toBeVisible();
	});
});
