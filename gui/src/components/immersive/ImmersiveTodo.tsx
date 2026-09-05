import {Check, ListChecks, Plus} from 'lucide-react';
import {useState} from 'react';
import {useChatStore} from '@/stores/chatStore';
import {cn} from '@/lib/utils';
import type {TodoItemView, TodoSnapshot} from '@/lib/toolActivity';

function makeSnap(todos: TodoItemView[]): TodoSnapshot {
	return {id: `immersive-${Date.now()}`, todos, running: false};
}

export function ImmersiveTodo() {
	const activeId = useChatStore(s => s.activeId);
	const snap = useChatStore(s =>
		activeId ? (s.sessionTodosById?.[activeId] ?? null) : null,
	);
	const [draft, setDraft] = useState('');

	const setTodos = (todos: TodoItemView[]) => {
		if (!activeId) {
			return;
		}
		useChatStore.setState(s => ({
			sessionTodosById: {
				...s.sessionTodosById,
				[activeId]: snap ? {...snap, todos} : makeSnap(todos),
			},
		}));
	};

	const add = () => {
		const text = draft.trim();
		if (!text) {
			return;
		}
		setTodos([...(snap?.todos ?? []), {content: text, status: 'pending', activeForm: ''}]);
		setDraft('');
	};

	const toggle = (i: number) => {
		const next = (snap?.todos ?? []).map((t, idx) =>
			idx === i
				? {...t, status: (t.status === 'completed' ? 'pending' : 'completed') as TodoItemView['status']}
				: t,
		);
		setTodos(next);
	};

	const todos = snap?.todos ?? [];
	const done = todos.filter(t => t.status === 'completed').length;

	return (
		<div className="xy-immersive-panel flex h-full max-h-full w-72 flex-col rounded-2xl">
			<div className="flex items-center gap-2 px-4 pt-3 pb-2">
				<ListChecks className="size-4 text-accent" />
				<span className="text-[13px] font-medium text-ink-soft">今日待办</span>
				<span className="ml-auto rounded-full bg-paper-deep px-2 py-0.5 font-mono text-[10px] text-mute">
					{done}/{todos.length}
				</span>
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto px-2">
				{todos.length ? (
					<ul className="space-y-0.5">
						{todos.map((t, i) => (
							<li key={`${i}-${t.content}`}>
								<button
									type="button"
									className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-paper-deep/40"
									onClick={() => toggle(i)}
								>
									<span
										className={cn(
											'mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border',
											t.status === 'completed'
												? 'border-ok bg-ok text-paper'
												: 'border-mute/50 text-transparent',
										)}
									>
										<Check className="size-3" strokeWidth={3} />
									</span>
									<span
										className={cn(
											'min-w-0 flex-1 text-[12px] leading-snug',
											t.status === 'completed'
												? 'text-mute line-through'
												: 'text-ink-soft',
										)}
									>
										{t.content}
									</span>
								</button>
							</li>
						))}
					</ul>
				) : (
					<div className="px-2 py-3 text-[12px] text-mute">暂无待办</div>
				)}
			</div>

			<div className="flex items-center gap-2 border-t border-line/50 px-3 py-2">
				<input
					value={draft}
					onChange={e => setDraft(e.target.value)}
					onKeyDown={e => {
						if (e.key === 'Enter') {
							add();
						}
					}}
					placeholder="添加今日待办…"
					className="min-w-0 flex-1 bg-transparent text-[12px] text-ink placeholder:text-mute focus:outline-none"
				/>
				<button
					type="button"
					className="xy-press flex size-6 items-center justify-center rounded-full bg-accent text-paper"
					onClick={add}
				>
					<Plus className="size-3.5" />
				</button>
			</div>
		</div>
	);
}
