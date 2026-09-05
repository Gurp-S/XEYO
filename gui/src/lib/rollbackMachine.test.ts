import {describe, expect, it} from 'vitest';
import {
	isRecoverableRollbackPhase,
	isTransientRollbackPhase,
	legacyStatusToPhase,
	phaseToLegacyStatus,
	ROLLBACK_EVENTS,
	ROLLBACK_PHASES,
	transitionRollbackPhase,
} from './rollbackMachine';

describe('rollbackMachine', () => {
	it('maps legacy status to phase and back', () => {
		expect(legacyStatusToPhase('loading')).toBe('previewing');
		expect(phaseToLegacyStatus('previewing')).toBe('loading');
		expect(phaseToLegacyStatus('committed_resend_failed')).toBe('error');
		expect(phaseToLegacyStatus('optimistic')).toBe('executing');
		expect(phaseToLegacyStatus('workspace_pending')).toBe('executing');
	});

	it('exhaustively applies expected transitions', () => {
		const expected: Partial<
			Record<
				string,
				Partial<Record<(typeof ROLLBACK_EVENTS)[number]['type'], string>>
			>
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
			blocked: {CANCEL: 'idle', RESET: 'idle'},
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
			completed: {RESET: 'idle'},
			failed: {RESET: 'idle', CANCEL: 'idle'},
		};

		for (const phase of ROLLBACK_PHASES) {
			for (const event of ROLLBACK_EVENTS) {
				const next = transitionRollbackPhase(phase, event);
				const want = expected[phase]?.[event.type];
				if (want) {
					expect(next).toBe(want);
				} else {
					expect(next).toBe(phase);
				}
			}
		}
	});

	it('flags transient and recoverable phases', () => {
		expect(isTransientRollbackPhase('ready')).toBe(true);
		expect(isTransientRollbackPhase('optimistic')).toBe(true);
		expect(isTransientRollbackPhase('workspace_pending')).toBe(true);
		expect(isTransientRollbackPhase('committed_resend_failed')).toBe(false);
		expect(isRecoverableRollbackPhase('committed_truncating')).toBe(true);
		expect(isRecoverableRollbackPhase('failed')).toBe(false);
	});
});
