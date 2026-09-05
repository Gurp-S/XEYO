import {ListTodo, MessageCircle, X} from 'lucide-react';

import {cn} from '@/lib/utils';
import {useChatUiStore} from '@/stores/chatUiStore';

export function ModeChip() {
	const agentMode = useChatUiStore(s => s.agentMode);
	const setAgentMode = useChatUiStore(s => s.setAgentMode);
	if (agentMode === 'agent') {
		return null;
	}
	const label = agentMode === 'plan' ? 'Plan' : 'Ask';
	const Icon = agentMode === 'plan' ? ListTodo : MessageCircle;

	return (
		<div className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full border border-line/80 bg-paper/70 px-2 font-mono text-[11px] text-ink-soft">
			<Icon className="h-3.5 w-3.5 text-accent" strokeWidth={1.9} />
			<span>{label}</span>
			<button
				type="button"
				aria-label={`退出 ${label} 模式`}
				title={`退出 ${label} 模式`}
				className={cn(
					'flex h-5 w-5 items-center justify-center rounded-full text-mute',
					'hover:bg-paper-deep hover:text-ink',
				)}
				onClick={() => setAgentMode('agent')}
			>
				<X className="h-3 w-3" strokeWidth={2} />
			</button>
		</div>
	);
}
