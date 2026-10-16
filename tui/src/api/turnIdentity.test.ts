import assert from 'node:assert/strict';
import test from 'node:test';
import {interruptSession} from './sse.js';
import {rememberTurnIdentity} from './turnIdentity.js';

test('interrupt captures observed turn A even when a new turn appears', async () => {
  const oldFetch = globalThis.fetch;
  let posted: Record<string, string> = {};
  rememberTurnIdentity('turn-test', {xy: {turn_id: 'A'}});
  globalThis.fetch = async (_url, options) => {
    posted = JSON.parse(String(options?.body));
    rememberTurnIdentity('turn-test', {xeyo_turn_id: 'B'});
    return new Response(JSON.stringify({ok: true}));
  };
  try {
    await interruptSession('http://localhost', '', 'turn-test');
    assert.equal(posted.expected_turn_id, 'A');
  } finally {globalThis.fetch = oldFetch;}
});
