import {describe, expect, it} from 'vitest';
import {roundActivities, toolCallLabel} from './roundActivity';
import type {ToolView, TranscriptBlock} from './groupTranscript';

const tool = (id: string, name = 'Read', status: ToolView['status'] = 'done'): ToolView => ({id,name,status,input:'{"file_path":"src/a.ts"}',result:'contents',createdAt:1});
const turn = (items: Extract<TranscriptBlock,{kind:'turn'}>['items'], live = false): TranscriptBlock => ({kind:'turn',id:'t',items,active:live});

describe('round activity from real transcript', () => {
 it('keeps repeated tools, failure and correction in received order', () => {
  const blocks = [turn([
   {kind:'assistant',message:{id:'p',role:'assistant',text:'先读取现有代码。',createdAt:1}},
   {kind:'tool',tool:tool('r1')}, {kind:'tool',tool:tool('r2')},
   {kind:'tool',tool:tool('bad','Bash','error')},
   {kind:'tool',tool:tool('fix','Edit')}, {kind:'tool',tool:tool('retry','Bash')},
   {kind:'assistant',message:{id:'final',role:'assistant',text:'完成。',createdAt:2}},
  ])];
  const events = roundActivities(blocks,true);
  expect(events.map(e=>e.id)).toEqual(['p','r1','r2','bad','fix','retry']);
  expect(events.map(e=>e.label)).toEqual(['回复','读取','读取','命令','修改','命令']);
  expect(events[3].error).toBe(true);
  expect(events[1].text).toBe('先读取现有代码。');
 });
 it('exposes actual thinking and streamed replies while retaining waiting results', () => {
  const pending = {...tool('r'),status:'running' as const,waiting:true,reasoningBefore:'需要先确认接口。'};
  const block = {...turn([{kind:'tool',tool:pending}],true),thinking:'比较两种实现。',streaming:'正在检查'};
  const events = roundActivities([block],false);
  expect(events.map(e=>e.label)).toEqual(['思考','读取','思考','回复']);
  expect(events[1]).toMatchObject({live:true,waiting:true,tool:pending});
  expect(events.at(-1)).toMatchObject({text:'正在检查',live:true});
 });
 it('does not invent stages for an empty or reply-only task', () => {
  expect(roundActivities([],false)).toEqual([]);
  const blocks = [turn([{kind:'assistant',message:{id:'a',role:'assistant',text:'答案',createdAt:1}}])];
  expect(roundActivities(blocks,false).map(e=>e.label)).toEqual(['回复']);
  expect(roundActivities(blocks,true)).toEqual([]);
 });
 it('retains command arguments without requiring JSON', () => {
  expect(toolCallLabel({...tool('x','Bash'),input:'npm test'})).toBe('Bash npm test');
 });
 it('keeps completed thought visible when the next tool arrives and ignores empty stream placeholders', () => {
  const block = {...turn([
   {kind:'assistant' as const,message:{id:'thought',role:'assistant' as const,isThought:true,text:'需要先读取已有实现，然后确定修改范围。',createdAt:1}},
   {kind:'tool' as const,tool:tool('next','Read','running')},
  ],true),streaming:'\u200b'};
  const events=roundActivities([block],false);
  expect(events.map(e=>e.id)).toEqual(['thought','next']);
  expect(events.at(-1)?.text).toBe('需要先读取已有实现，然后确定修改范围。');
 });
 it('does not select raw XML tool markup as an empty reply', () => {
  const block={...turn([{kind:'tool' as const,tool:{...tool('next'),reasoningBefore:'先确认这个文件。'}}],true),streaming:'<tool_call>Read\n<arg_key>file_path</arg_key><arg_value>a.ts'};
  expect(roundActivities([block],false).map(e=>e.id)).toEqual(['next:thought','next']);
 });
});
