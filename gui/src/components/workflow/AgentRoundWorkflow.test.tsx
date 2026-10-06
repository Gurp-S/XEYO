// @vitest-environment jsdom
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import type {TranscriptBlock} from '@/lib/groupTranscript';
import {AgentRoundWorkflow} from './AgentRoundWorkflow';
vi.mock('../StreamingMarkdown',()=>({StreamingMarkdown:({text}:{text:string})=><div>{text}</div>}));
afterEach(cleanup);
const blocks: TranscriptBlock[] = [{kind:'turn',id:'turn',active:true,items:[
 {kind:'tool',tool:{id:'read',name:'Read',input:'{"file_path":"a.ts"}',result:'actual file contents',status:'done',createdAt:1}},
 {kind:'tool',tool:{id:'cmd',name:'Bash',input:'{"command":"npm test"}',result:'test output',status:'running',createdAt:2}},
]}];
describe('workflow history interaction',()=>{
 it('keeps tool output collapsed and remembers expansion across selection',async()=>{
  render(<AgentRoundWorkflow blocks={blocks} settled={false} signalLive={false} status=""/>);
  expect(screen.queryByText('test output')).toBeNull();
  fireEvent.click(screen.getByText('Bash npm test'));
  expect(await screen.findByText('test output')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'读取了(a.ts)'}));
  expect(screen.queryByText('actual file contents')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'执行(npm test)'}));
  expect(await screen.findByText('test output')).toBeTruthy();
 });
 it('holds the chosen history record as live events arrive, then follows latest on request',()=>{
  const {rerender}=render(<AgentRoundWorkflow blocks={blocks} settled={false} signalLive={false} status=""/>);
  fireEvent.click(screen.getByRole('button',{name:'读取了(a.ts)'}));
  const live: TranscriptBlock[] = [{...blocks[0] as Extract<TranscriptBlock,{kind:'turn'}>,streaming:'new streamed response'}];
  rerender(<AgentRoundWorkflow blocks={live} settled={false} signalLive={false} status=""/>);
  expect(screen.queryByText('new streamed response')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'回到最新'}));
  expect(screen.getByText('new streamed response')).toBeTruthy();
 });
});
