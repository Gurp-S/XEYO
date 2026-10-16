import {useEffect} from 'react';
import {useChatStore} from '@/stores/chatStore';

/** Background workers can outlive the parent's SSE connection. */
export function useBackgroundAgents() {
	useEffect(() => {
		let disposed = false;
		let timer: ReturnType<typeof setTimeout>;
		const poll = async () => {
			const state = useChatStore.getState();
			const sessions = Object.entries(state.multiAgentTasksBySession)
				.filter(([, tasks]) => tasks.some(task => task.status === 'running' || task.status === 'pending'))
				.map(([sid]) => sid);
			await Promise.allSettled(sessions.map(sid => state.loadAgentsFor(sid)));
			if (!disposed) timer = setTimeout(() => void poll(), 2000);
		};
		void poll();
		return () => { disposed = true; clearTimeout(timer); };
	}, []);
}
