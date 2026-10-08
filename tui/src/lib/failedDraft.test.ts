import {test} from 'node:test';
import assert from 'node:assert/strict';
import {restoreFailedDraft} from './failedDraft.js';

test('restores submitted text only while the input remains empty', () => {
	assert.equal(restoreFailedDraft('', 'failed message'), 'failed message');
	assert.equal(restoreFailedDraft('next draft', 'failed message'), 'next draft');
});
