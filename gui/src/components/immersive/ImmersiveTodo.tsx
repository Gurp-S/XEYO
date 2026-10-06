import {Check, ListChecks} from 'lucide-react';
import {useChatStore} from '@/stores/chatStore';
import {cn} from '@/lib/utils';

/**
 * 沉浸侧板的今日待办：sessionTodosById 的只读镜像（F6 统一只读）。
 *
 * 这里曾有勾选/新增（只写本地镜像、零回路到模型，下一次模型 todo 事件
 * 整表替换时被静默覆盖）。与 Composer 侧 SessionTodoDock 和 Claude 的
 * TodoWrite 展示口径一致：只展示模型给的事实，不提供人侧编辑。
 */
export function ImmersiveTodo() {
	const activeId = useChatStore(s => s.activeId);
	const snap = useChatStore(s =>
		activeId ? (s.sessionTodosById?.[activeId] ?? null) : null,
	);

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

			<div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
				{todos.length ? (
					<ul className="space-y-0.5">
						{todos.map((t, i) => (
							<li
								key={`${i}-${t.content}`}
								className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left"
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
							</li>
						))}
					</ul>
				) : (
					<div className="px-2 py-3 text-[12px] text-mute">暂无待办</div>
				)}
			</div>
		</div>
	);
}
