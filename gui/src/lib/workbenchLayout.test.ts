import {describe,it,expect} from 'vitest';
import {clampToolWidth,workbenchLayout} from './workbenchLayout';
import {bytesToStorageDraft,storageDraftToBytes} from '@/components/settings/storageUnits';
import {collectCalls,callSummary} from './toolCallHistory';

describe('task-appropriate workspace layout',()=>{
 it('uses the main body in narrow hosts and a separate saved width in wide hosts',()=>{
  expect(workbenchLayout('browser',667,248,560).focused).toBe(true);
  expect(workbenchLayout('terminal',1000,248,600)).toEqual({wide:true,focused:false,width:600});
  expect(workbenchLayout('terminal',850,248,600).width).toBe(510);
  expect(workbenchLayout(null,667,248,600)).toEqual({wide:false,focused:false,width:248});
  expect(clampToolWidth(NaN)).toBe(560);
 });
 it('preserves byte precision across storage unit editing and rejects invalid limits',()=>{
  for(const bytes of [0,1,1024,104857600,123456789])expect(storageDraftToBytes(bytesToStorageDraft(bytes))).toEqual({ok:true,value:bytes});
  expect(storageDraftToBytes('')).toEqual({ok:true,value:null});
  for(const bad of ['bad','-1','Infinity','1e20'])expect(storageDraftToBytes(bad).ok).toBe(false);
 });
 it('keeps shell copy text and other tool JSON intact while extracting readable summaries',()=>{
  const raw=JSON.stringify({query:'search\\n literal'});
  const calls=collectCalls([{id:'u',role:'user',text:'test',createdAt:1},{id:'t1',role:'tool',toolName:'Bash',toolUseId:'bash',toolInput:JSON.stringify({command:'echo first\necho second'}),toolStatus:'done',text:'done',createdAt:2},{id:'t2',role:'tool',toolName:'Search',toolUseId:'search',toolInput:raw,toolStatus:'done',text:'done',createdAt:3}]);
  expect(calls.map(c=>c.display)).toEqual(['echo first\necho second',raw]);
  expect(callSummary(calls[1].name,calls[1].input,calls[1].display)).toBe('search\\n literal');
  expect(new Set(calls.map(c=>c.id)).size).toBe(2);
 });
});
