import {afterEach,expect,it,vi} from 'vitest';
import {reorderInbox} from './inboxOrder';
afterEach(()=>vi.unstubAllGlobals());
it.each([
	[{ok:true,session_id:'sid',order:['b','a']},true],
	[{ok:true,session_id:'other',order:['b','a']},false],
	[{ok:true,session_id:'sid',order:['a','b']},false],
	[{ok:true,session_id:'sid',order:['b']},false],
	[{ok:false,session_id:'sid',order:['b','a']},false],
])('requires an exact order and session receipt: %j',async(receipt,accepted)=>{
	const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt),{status:200}));vi.stubGlobal('fetch',fetch);
	expect(await reorderInbox('sid',['a','b'],['b','a'])).toBe(accepted);
	expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({expected_order:['a','b'],order:['b','a']});
});
