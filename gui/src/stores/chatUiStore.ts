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
 * 共享聊天组件改用此 hook，而不是把自己绑死在
 * Agent store 上。默认仍指向主 Agent store，因此主页面的
 * 行为不变；SideChatPanel 提供自己隔离的 store provider。
 */
export function useChatUiStore<T>(selector: (state: ChatState) => T): T {
	const store = useContext(ChatUiStoreContext);
	return (store ?? useChatStore)(selector);
}

export function useChatUiStoreApi(): ChatUiStore {
	return useContext(ChatUiStoreContext) ?? useChatStore;
}
