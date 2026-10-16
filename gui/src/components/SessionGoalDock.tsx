import type {SessionGoalState} from '@/lib/api/goals';
import {useSessionGoalLive} from '@/hooks/useSessionGoalLive';
import {isGoalLive} from '@/lib/goalSync';
import {useChatStore} from '@/stores/chatStore';
import {GoalDockCard} from './composer/GoalDockCard';
export {useSessionGoalLive};

export function SessionGoalDock({embedded=false}: {embedded?:boolean}) {
 const id=useChatStore(s=>s.activeId);
 const state=useChatStore(s=>id?s.sessionGoalById[id]:undefined);
 const archived=useChatStore(s=>Boolean(id&&s.sessions.find(session=>session.id===id)?.archived));
 useSessionGoalLive(id);
 if(!id||!isGoalLive(state)||!state)return null;
 return <div className={embedded?undefined:'shrink-0 px-3 pt-1 sm:px-5'}><GoalDockCard key={`${id}:${state.goal.goal_id}:${archived}`} sessionId={id} goal={state.goal} archived={archived}/></div>;
}
export function goalDockLiveFor(state:SessionGoalState|null|undefined): boolean {return isGoalLive(state);}
export function useSessionGoalDockLive():boolean {
 const id=useChatStore(s=>s.activeId);
 const state=useChatStore(s=>id?s.sessionGoalById[id]:undefined);
 return Boolean(id)&&goalDockLiveFor(state);
}
