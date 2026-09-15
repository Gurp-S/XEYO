/**
 * Chat store 门面——组合 ./chat/* 内的领域 slice。
 */
import {create} from 'zustand';
import {DEFAULT_SPACE_ID} from '@/lib/db';
import type {ChatState} from './chat/preStoreHelpers';
import {loadCollapsed} from './chat/spaceHelpers';
import {createUiChromeSlice, savedPendingPermission} from './chat/uiChromeSlice';
import {createStreamSendSlice} from './chat/streamSendSlice';
import {createSpaceSessionSlice} from './chat/spaceSessionSlice';
import {createRemoteMirrorSlice} from './chat/remoteMirrorSlice';
import {createMultiAgentSlice} from './chat/multiAgentSlice';
import {createInboxSlice} from './chat/inboxSlice';

export type {ChatState, SessionUsageView, PendingPermissionInfo, PendingAskInfo, PendingPlanInfo} from './chat/preStoreHelpers';
export {AGENT_VIEW_MAIN, currentAgentView} from './chat/preStoreHelpers';

export const useChatStore = create<ChatState>((set, get) => ({
	hydrated: false,
	spaces: [],
	sessions: [],
	activeId: null,
	activeSpaceId: DEFAULT_SPACE_ID,
	collapsedSpaces: loadCollapsed(),
	messagesById: {},
	messagesLoadingIds: {},
	historyById: {},
	sessionTodosById: {},
	sessionGoalById: {},
	sessionJobsById: {},
	inboxBySession: {},
	sessionUsageById: {},
	rollbackById: {},
	pendingPermission: savedPendingPermission,
	agentMode: 'agent',
	sessionStreams: {},
	recoveryBySession: {},
	errorBanner: null,
	errorBannerSessionId: null,
	sidebarOpen: true,
	immersive: false,
	searchFocusSeq: 0,
	composerInsertSeq: 0,
	lastComposerInsert: null,
	composerFocusSeq: 0,
	emptyQuipSeq: 0,
	...createMultiAgentSlice(set, get),
	...createInboxSlice(set, get),
	...createSpaceSessionSlice(set, get),
	...createUiChromeSlice(set, get),
	...createStreamSendSlice(set, get),
	...createRemoteMirrorSlice(set, get),
}));
