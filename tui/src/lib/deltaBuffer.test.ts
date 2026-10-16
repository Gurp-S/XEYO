import test from 'node:test';
import assert from 'node:assert/strict';
import {createDeltaBuffer} from './deltaBuffer.js';
import {appendAssistantDelta} from './queuedTimeline.js';
import type {TimelineItem} from '../types.js';

test('batches deltas while keeping text, identities and tool boundaries', () => {
  let items: TimelineItem[] = [{id: 'placeholder', kind: 'assistant', text: '', streaming: true}];
  let writes = 0;
  const buffer = createDeltaBuffer((id, text, previous) => {
    writes++;
    items = appendAssistantDelta(items, id, text, previous);
  });
  buffer.push('a', 'one', 'placeholder');
  buffer.push('a', ' two', 'a');
  assert.equal(writes, 0);
  buffer.flush(); // tool boundary
  items.push({id: 'tool', kind: 'tool', name: 'Read', summary: '', status: 'completed'});
  buffer.push('b', 'three', 'a');
  buffer.push('c', 'four', 'b'); // changing identity flushes b
  buffer.flush(); // done/error/abort boundary
  buffer.flush();
  assert.equal(writes, 3);
  assert.deepEqual(items.map(i => i.id), ['a', 'tool', 'b', 'c']);
  assert.equal((items[0] as {text: string}).text, 'one two');
});

test('a quiet stream flushes without waiting for completion', async () => {
  const chunks: string[] = [];
  const buffer = createDeltaBuffer((_id, text) => chunks.push(text), 5);
  buffer.push('a', 'partial', 'placeholder');
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.deepEqual(chunks, ['partial']);
  buffer.flush();
  assert.deepEqual(chunks, ['partial']);
});
