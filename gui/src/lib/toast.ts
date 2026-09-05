/**
 * 框架无关的微型 toast 订阅 store（不依赖 React/zustand）。
 * 非组件层（stores / lib）可直接调用；UI 由 components/ToastHost.tsx 渲染。
 */

export type ToastKind = 'success' | 'error' | 'warn' | 'info';

export interface ToastAction {
	label: string;
	onClick: () => void;
}

export interface ToastItem {
	id: number;
	kind: ToastKind;
	msg: string;
	action?: ToastAction;
	/** 自动过期毫秒数（error 6s，其余 4s） */
	duration: number;
	createdAt: number;
}

const MAX_ITEMS = 4;
const DEFAULT_MS = 4000;
const ERROR_MS = 6000;
const DEDUPE_MS = 1500;

let seq = 0;
let items: readonly ToastItem[] = [];
const listeners = new Set<() => void>();
const timers = new Map<number, ReturnType<typeof setTimeout>>();

function emit() {
	for (const fn of [...listeners]) {
		fn();
	}
}

function scheduleExpire(item: ToastItem) {
	timers.set(
		item.id,
		setTimeout(() => dismiss(item.id), item.duration),
	);
}

function push(kind: ToastKind, msg: string, action?: ToastAction): void {
	const now = Date.now();
	// 同文案短时间内去重：忽略重复推送
	if (items.some(it => it.msg === msg && now - it.createdAt < DEDUPE_MS)) {
		return;
	}
	// 超出上限挤掉最旧
	while (items.length >= MAX_ITEMS) {
		dismiss(items[0].id);
	}
	const item: ToastItem = {
		id: ++seq,
		kind,
		msg,
		action,
		duration: kind === 'error' ? ERROR_MS : DEFAULT_MS,
		createdAt: now,
	};
	items = [...items, item];
	scheduleExpire(item);
	emit();
}

export function dismiss(id: number): void {
	const t = timers.get(id);
	if (t !== undefined) {
		clearTimeout(t);
		timers.delete(id);
	}
	const next = items.filter(it => it.id !== id);
	if (next.length === items.length) {
		return;
	}
	items = next;
	emit();
}

export const toast = {
	success(msg: string): void {
		push('success', msg);
	},
	error(msg: string, action?: ToastAction): void {
		push('error', msg, action);
	},
	warn(msg: string, action?: ToastAction): void {
		push('warn', msg, action);
	},
	info(msg: string, action?: ToastAction): void {
		push('info', msg, action);
	},
	dismiss,
	/** 订阅变更；返回取消订阅函数。快照引用仅在条目增删时更换（适配 useSyncExternalStore）。 */
	_sub(fn: () => void): () => void {
		listeners.add(fn);
		return () => {
			listeners.delete(fn);
		};
	},
	_items(): readonly ToastItem[] {
		return items;
	},
};
