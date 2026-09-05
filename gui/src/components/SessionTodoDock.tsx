import {useReducer, useRef} from 'react';
import {
	dismissTodoSnapshot,
	isTodoSnapshotDismissed,
} from '@/lib/todoDismissals';
import type {TodoSnapshot} from '@/lib/toolActivity';
import {useChatStore} from '@/stores/chatStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {DockPresence} from './DockPresence';
import {TodoList} from './TodoList';

type Props = {
	/** 嵌入 Composer 统一外框时不包外层 padding。 */
	embedded?: boolean;
};

/**
 * 输入框上方的 Todo 停靠栏。
 * 仅读取 sessionTodosById — 无 transcript props（避免省略时崩溃）。
 * 生命周期：轮次中 TodoWrite → 实时更新 → 回复结束 / 关闭时隐藏。
 */
export function SessionTodoDock({embedded = false}: Props) {
	const activeId = useChatStore(s => s.activeId);
	const snapshot = useChatStore(s =>
		activeId ? (s.sessionTodosById?.[activeId] ?? null) : null,
	);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const [, bump] = useReducer((n: number) => n + 1, 0);
	const holdRef = useRef<TodoSnapshot | null>(null);

	const dismissed =
		Boolean(activeId) &&
		Boolean(snapshot) &&
		isTodoSnapshotDismissed(activeId!, snapshot!.id);

	const live =
		Boolean(activeId) &&
		Boolean(snapshot) &&
		snapshot!.todos.length > 0 &&
		!dismissed;

	if (snapshot && snapshot.todos.length > 0) {
		holdRef.current = snapshot;
	}

	const display = live ? snapshot : holdRef.current;
	const sessionId = activeId;

	const panel =
		display && sessionId ? (
			<TodoList
				snapshot={display}
				dock
				onDismiss={() => {
					dismissTodoSnapshot(sessionId, display.id);
					useChatStore.setState(s => ({
						sessionTodosById: {
							...s.sessionTodosById,
							[sessionId]: null,
						},
					}));
					bump();
				}}
			/>
		) : null;

	return (
		<DockPresence open={live} smoothness={smoothness}>
			{panel
				? embedded
					? panel
					: (
						<div className="shrink-0 px-3 pt-1 sm:px-5">
							<div className="mx-auto w-full max-w-3xl">{panel}</div>
						</div>
					)
				: null}
		</DockPresence>
	);
}

/** Todo 面板是否应在 Composer 统一外框中显示。 */
export function useSessionTodoDockLive(): boolean {
	const activeId = useChatStore(s => s.activeId);
	const snapshot = useChatStore(s =>
		activeId ? (s.sessionTodosById?.[activeId] ?? null) : null,
	);
	if (!activeId || !snapshot || snapshot.todos.length === 0) {
		return false;
	}
	return !isTodoSnapshotDismissed(activeId, snapshot.id);
}
