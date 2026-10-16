import {beforeEach,expect,it,vi} from 'vitest';
import {createInboxSlice} from './inboxSlice';
import type {ChatState} from './preStoreHelpers';
const io=vi.hoisted(()=>({reorder:vi.fn(),snapshot:vi.fn()}));
vi.mock('@/lib/api/inboxOrder',()=>({reorderInbox:io.reorder}));
vi.mock('@/lib/api',async original=>({...await original<typeof import('@/lib/api')>(),inboxSnapshot:io.snapshot}));
beforeEach(()=>{vi.resetAllMocks();io.snapshot.mockResolvedValue(null);});
function fixture() {
	let state={sessions:[{id:'gui'}],historyById:{gui:{activeBranch:{branchId:'main',backendSessionId:'backend'}}},inboxBySession:{gui:[{queue_id:'a',state:'queued',text:'A'},{queue_id:'inflight',state:'delivering',text:'Sending'},{queue_id:'b',state:'queued',text:'B'}]}} as unknown as ChatState;
	const get=()=>state;
	const set=(patch:Partial<ChatState>|((state:ChatState)=>Partial<ChatState>))=>{state={...state,...typeof patch==='function'?patch(state):patch};};
	Object.assign(state,createInboxSlice(set,get));return {get,set};
}
it('applies acknowledged order only to pending slots and keeps in-flight identity',async()=>{
	const f=fixture();io.reorder.mockResolvedValue(true);await f.get().reorderInboxItems('gui',['a','b'],['b','a']);
	expect(io.reorder).toHaveBeenCalledWith('backend',['a','b'],['b','a']);
	expect(f.get().inboxBySession.gui.map(item=>[item.queue_id,item.position])).toEqual([['b',1],['inflight',0],['a',2]]);
});
it('a late reorder acknowledgement cannot reorder the new branch',async()=>{
	const f=fixture();let release!:(ok:boolean)=>void;io.reorder.mockReturnValue(new Promise<boolean>(resolve=>{release=resolve;}));
	const work=f.get().reorderInboxItems('gui',['a','b'],['b','a']);
	f.set({historyById:{gui:{activeBranch:{branchId:'new',backendSessionId:'new'}}} as never,inboxBySession:{gui:[]}});const changed=f.get();release(true);await work;
	expect(f.get()).toBe(changed);expect(io.snapshot).not.toHaveBeenCalled();
});
