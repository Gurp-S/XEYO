import {useMemo} from 'react';
import {useChatStore} from '@/stores/chatStore';
import {useWorkspaceVisible} from '@/hooks/useWorkspaceVisible';
import {createWorkbenchChangesProjection} from '@/lib/workbenchChangesProjection';
import type {ChangedFile} from '@/lib/toolActivity';
import type {ChatMessage} from '@/lib/types';

const EMPTY: ChatMessage[] = [];
const EMPTY_FILES: ChangedFile[] = [];

/** The latest delivered user request defines a round, regardless of tool order. */
export function useWorkbenchChanges(messageId?: string, enabled = true) {
 const visible = useWorkspaceVisible();
 const project = useMemo(() => createWorkbenchChangesProjection(), []);
 // Keep panel state mounted, but subscribe to messages only while it uses them.
 const messages = useChatStore(s => enabled && visible && s.activeId ? s.messagesById[s.activeId] ?? EMPTY : EMPTY);
 return useMemo(() => messages.length ? project(messages, messageId) : EMPTY_FILES, [messages, messageId, project]);
}
