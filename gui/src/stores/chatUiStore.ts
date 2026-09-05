import {createContext, createElement, useContext} from 'react';
import type {ReactNode} from 'react';
import type {ChatState} from './chatStore';
import {useChatStore} from './chatStore';

type ChatUiStore = typeof useChatStore;

const ChatUiStoreContext = createContext<ChatUiStore | null>(null);

export function ChatUiStoreProvider({
	store,
	children,
}: {
	store: ChatUiStore;
	children: ReactNode;
}) {
	return createElement(ChatUiStoreContext.Provider, {value: store}, children);
}

/**
 * Shared chat components use this hook instead of binding themselves to the
 * Agent store. The default remains the main Agent store, so the main page's
 * behavior is unchanged; SideChatPanel supplies its isolated store provider.
 */
export function useChatUiStore<T>(selector: (state: ChatState) => T): T {
	const store = useContext(ChatUiStoreContext);
	return (store ?? useChatStore)(selector);
}

export function useChatUiStoreApi(): ChatUiStore {
	return useContext(ChatUiStoreContext) ?? useChatStore;
}
