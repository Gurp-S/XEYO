import test from 'node:test';
import assert from 'node:assert/strict';
import {appendAssistantDelta, mergeQueuedTimeline} from './queuedTimeline.js';
import type {TimelineItem} from '../types.js';

test('distinct model calls keep their identities and tool order', () => {
  let items: TimelineItem[] = [{id: 'placeholder', kind: 'assistant', text: '', streaming: true}];
  items = appendAssistantDelta(items, 'answer-1', 'before tool', 'placeholder');
  items.push({id: 'tool', kind: 'tool', name: 'Read', summary: '', status: 'completed'});
  items = appendAssistantDelta(items, 'answer-2', 'after tool', 'answer-1');
  assert.deepEqual(items.map(item => item.id), ['answer-1', 'tool', 'answer-2']);
  assert.equal((items[0] as any).streaming, false);
});

test('canonical batch folds queued aliases without deduplicating identical answers', () => {
  const local: TimelineItem[] = [
    {id: 'first-user', kind: 'user', text: 'first'},
    {id: 'first-reply', kind: 'assistant', text: 'same'},
    {id: 'A', kind: 'user', text: 'A'}, {id: 'B', kind: 'user', text: 'B'},
    {id: 'receipt', kind: 'system', text: 'queued'},
    {id: 'batch-reply', kind: 'assistant', text: 'same'},
  ];
  const server: TimelineItem[] = [local[0]!, local[1]!, {id: 'A', kind: 'user', text: 'A\nB'}, local[5]!];
  const merged = mergeQueuedTimeline(local, server, new Set(['B', 'receipt']));
  assert.deepEqual(merged, server.map(item => item.kind === 'assistant' ? {...item, streaming: false} : item));
});
