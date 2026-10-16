/** Backend branch and agent attempt fence every asynchronous card operation. */
import {activeBackendSessionId, type ChatState} from '@/stores/chat/preStoreHelpers';

export function agentRequestScope(state: ChatState, sid: string, aid: string) {
    return {
        backendSid: activeBackendSessionId(state.historyById, sid),
        attemptId: [...(state.multiAgentTasksBySession[sid] ?? [])].reverse().find(t => t.agentId === aid)?.attemptId,
    };
}
export function agentScopeCurrent(state: ChatState, sid: string, aid: string, scope: ReturnType<typeof agentRequestScope>, resultAttempt?: string) {
    if (!state.sessions.some(s => s.id === sid)) return false;
    const current = agentRequestScope(state, sid, aid);
    return scope.backendSid === current.backendSid &&
        (current.attemptId === scope.attemptId || (!!resultAttempt && current.attemptId === resultAttempt));
}
export function staleAgentEvent(state: ChatState, sid: string, aid: string, attempt?: string) {
    const current = agentRequestScope(state, sid, aid).attemptId;
    return !!current && current !== attempt;
}
