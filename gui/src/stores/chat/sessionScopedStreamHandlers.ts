import type {ChatStreamHandlers} from '@/lib/api';

/** Ignore stream callbacks after their local session has been removed. */
export function sessionScopedStreamHandlers(
	handlers: ChatStreamHandlers,
	sessionExists: () => boolean,
): ChatStreamHandlers {
	return new Proxy(handlers, {
		get(target, property, receiver) {
			const handler = Reflect.get(target, property, receiver);
			if (typeof handler !== 'function') return handler;
			return (...args: unknown[]) => {
				if (!sessionExists()) return;
				return handler.apply(target, args);
			};
		},
	});
}
