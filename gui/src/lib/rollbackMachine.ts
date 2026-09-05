import type {RollbackPhase} from '@/lib/types';

export type RollbackEvent =
	| {type: 'PREVIEW_START'}
	| {type: 'PREVIEW_OK'}
	| {type: 'PREVIEW_FAIL'}
	| {type: 'BLOCKED'}
	| {type: 'EXECUTE_START'}
	| {type: 'OPTIMISTIC'}
	| {type: 'WORKSPACE_PENDING'}
	| {type: 'COMMIT_FAILED'}
	| {type: 'RECOVERY_REQUIRED'}
	| {type: 'RECOVERY_RESOLVED'}
	| {type: 'COMMITTED'}
	| {type: 'TRUNCATE_FAIL'}
	| {type: 'RESEND_SENT'}
	| {type: 'RESEND_FAIL'}
	| {type: 'RETRY_RESEND'}
	| {type: 'CANCEL'}
	| {type: 'RESET'};

const TRANSITIONS: Record<
	RollbackPhase,
	Partial<Record<RollbackEvent['type'], RollbackPhase>>
> = {
	idle: {
		PREVIEW_START: 'previewing',
		EXECUTE_START: 'executing',
		RESET: 'idle',
		CANCEL: 'idle',
	},
	previewing: {
		PREVIEW_OK: 'ready',
		BLOCKED: 'blocked',
		PREVIEW_FAIL: 'failed',
		CANCEL: 'idle',
	},
	blocked: {
		CANCEL: 'idle',
		RESET: 'idle',
	},
	ready: {
		EXECUTE_START: 'executing',
		OPTIMISTIC: 'optimistic',
		CANCEL: 'idle',
	},
	executing: {
		OPTIMISTIC: 'optimistic',
		WORKSPACE_PENDING: 'workspace_pending',
		COMMITTED: 'committed_truncating',
		COMMIT_FAILED: 'failed',
		RECOVERY_REQUIRED: 'recovery_required',
		TRUNCATE_FAIL: 'failed',
		RESEND_FAIL: 'committed_resend_failed',
	},
	optimistic: {
		WORKSPACE_PENDING: 'workspace_pending',
		COMMITTED: 'committed_truncating',
		RESEND_SENT: 'completed',
		COMMIT_FAILED: 'failed',
		RECOVERY_REQUIRED: 'recovery_required',
		RESEND_FAIL: 'committed_resend_failed',
	},
	workspace_pending: {
		COMMITTED: 'committed_truncating',
		COMMIT_FAILED: 'failed',
		RECOVERY_REQUIRED: 'recovery_required',
		RESEND_SENT: 'completed',
		RESEND_FAIL: 'committed_resend_failed',
	},
	committed_truncating: {
		RESEND_SENT: 'completed',
		RESEND_FAIL: 'committed_resend_failed',
		TRUNCATE_FAIL: 'failed',
	},
	committed_resend_failed: {
		RESEND_SENT: 'completed',
		RESEND_FAIL: 'committed_resend_failed',
		RETRY_RESEND: 'committed_resend_failed',
		CANCEL: 'idle',
	},
	recovery_required: {
		RECOVERY_RESOLVED: 'idle',
		CANCEL: 'idle',
		RESET: 'idle',
	},
	completed: {
		RESET: 'idle',
	},
	failed: {
		RESET: 'idle',
		CANCEL: 'idle',
	},
};

export function transitionRollbackPhase(
	current: RollbackPhase,
	event: RollbackEvent,
): RollbackPhase {
	return TRANSITIONS[current]?.[event.type] ?? current;
}

export type RollbackLegacyStatus =
	| 'idle'
	| 'loading'
	| 'ready'
	| 'blocked'
	| 'executing'
	| 'success'
	| 'error';

export function phaseToLegacyStatus(phase: RollbackPhase): RollbackLegacyStatus {
	switch (phase) {
		case 'idle':
			return 'idle';
		case 'previewing':
			return 'loading';
		case 'ready':
			return 'ready';
		case 'blocked':
			return 'blocked';
		case 'executing':
		case 'optimistic':
		case 'workspace_pending':
		case 'committed_truncating':
			return 'executing';
		case 'committed_resend_failed':
		case 'recovery_required':
		case 'failed':
			return 'error';
		case 'completed':
			return 'success';
		default:
			return 'idle';
	}
}

export function legacyStatusToPhase(status: RollbackLegacyStatus): RollbackPhase {
	switch (status) {
		case 'idle':
			return 'idle';
		case 'loading':
			return 'previewing';
		case 'ready':
			return 'ready';
		case 'blocked':
			return 'blocked';
		case 'executing':
			return 'executing';
		case 'success':
			return 'completed';
		case 'error':
			return 'failed';
		default:
			return 'idle';
	}
}

export function isTransientRollbackPhase(phase: RollbackPhase): boolean {
	return (
		phase === 'previewing' ||
		phase === 'ready' ||
		phase === 'blocked' ||
		phase === 'executing' ||
		phase === 'optimistic' ||
		phase === 'workspace_pending' ||
		phase === 'recovery_required'
	);
}

export function isRecoverableRollbackPhase(phase: RollbackPhase): boolean {
	return (
		phase === 'committed_truncating' ||
		phase === 'committed_resend_failed' ||
		phase === 'recovery_required'
	);
}

export const ROLLBACK_PHASES: RollbackPhase[] = [
	'idle',
	'previewing',
	'blocked',
	'ready',
	'executing',
	'optimistic',
	'workspace_pending',
	'committed_truncating',
	'committed_resend_failed',
	'recovery_required',
	'completed',
	'failed',
];

export const ROLLBACK_EVENTS: RollbackEvent[] = [
	{type: 'PREVIEW_START'},
	{type: 'PREVIEW_OK'},
	{type: 'PREVIEW_FAIL'},
	{type: 'BLOCKED'},
	{type: 'EXECUTE_START'},
	{type: 'OPTIMISTIC'},
	{type: 'WORKSPACE_PENDING'},
	{type: 'COMMIT_FAILED'},
	{type: 'RECOVERY_REQUIRED'},
	{type: 'RECOVERY_RESOLVED'},
	{type: 'COMMITTED'},
	{type: 'TRUNCATE_FAIL'},
	{type: 'RESEND_SENT'},
	{type: 'RESEND_FAIL'},
	{type: 'RETRY_RESEND'},
	{type: 'CANCEL'},
	{type: 'RESET'},
];
