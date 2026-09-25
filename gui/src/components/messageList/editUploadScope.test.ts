import {describe, expect, it} from 'vitest';
import {isCurrentEditUpload, type EditUploadScope} from './editUploadScope';

const scope: EditUploadScope = {
	generation: 4,
	sessionId: 'session-a',
	messageId: 'message-a',
};

describe('isCurrentEditUpload', () => {
	it('accepts a completion for the same session, message, and edit generation', () => {
		expect(isCurrentEditUpload(scope, {...scope})).toBe(true);
	});

	it.each([
		['another session', {...scope, sessionId: 'session-b'}],
		['another message', {...scope, messageId: 'message-b'}],
		['a later edit', {...scope, generation: scope.generation + 1}],
		['no active editor', {...scope, messageId: null}],
	])('rejects a completion for %s', (_label, current) => {
		expect(isCurrentEditUpload(scope, current)).toBe(false);
	});
});
