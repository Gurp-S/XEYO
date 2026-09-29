import {
	createContext,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type MutableRefObject,
} from 'react';
import {flushSync} from 'react-dom';
import type {ChatMessage} from '@/lib/types';
import {StickyPromptController} from './StickyPromptController';

export const EditPortalHostContext = createContext<HTMLElement | null>(null);

export function useStickyPromptController(opts: {
	messagesRef: MutableRefObject<ChatMessage[]>;
	scrollerRef: MutableRefObject<HTMLElement | null>;
	contentRef: MutableRefObject<HTMLElement | null>;
	overlayRef: MutableRefObject<HTMLDivElement | null>;
	streaming: boolean;
	/** 气泡吸顶总开关（设置→外观；默认关）。关闭时 controller 零吸附、编辑就地展开。 */
	enabled?: boolean;
	/** 与 MessageList stickyLayoutMuteRef 对齐 */
	onLayoutMute?: () => void;
}) {
	const {
		messagesRef,
		scrollerRef,
		contentRef,
		overlayRef,
		streaming,
		enabled = true,
		onLayoutMute,
	} = opts;
	const [editPortalHost, setEditPortalHost] = useState<HTMLElement | null>(
		null,
	);

	const controller = useMemo(
		() =>
			new StickyPromptController({
				getMessages: () => messagesRef.current,
				onEditPortalHostChange: host => {
					/* 与 editingMessageId 同帧提交，避免编辑气泡先在流内撑开 */
					flushSync(() => {
						setEditPortalHost(host);
					});
				},
				onLayoutMute,
			}),
		// 故意只建一次；messages / mute 走 ref/callback
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[],
	);

	/* 总开关同步：controller 侧关闭即清残留；开启后跑一次 flush 让已注册 chip 立即接管。 */
	useEffect(() => {
		const wasEnabled = controller.isEnabled();
		controller.setEnabled(enabled);
		if (!wasEnabled && enabled) {
			controller.bindDom({
				scroller: scrollerRef.current,
				content: contentRef.current,
				overlay: overlayRef.current,
			});
			controller.flush();
		}
	}, [controller, enabled, scrollerRef, contentRef, overlayRef]);

	/* bindDom 只是三个字段赋值（对同一批节点幂等）。原先是无依赖数组的 effect：
	   MessageList 每渲染一次就重建一个绑定对象并重跑一次——流式期间每帧一次。
	   现在只在节点引用真的换了三态之一时才绑（同一批节点 → 完全等价）。
	   flushStuck（滚动 / 吸顶注册的热路径）共用同一守卫：省掉每次一个对象分配
	   与三次赋值，绑定结果与逐次重绑严格相同。 */
	const boundDomRef = useRef<{
		scroller: HTMLElement | null;
		content: HTMLElement | null;
		overlay: HTMLDivElement | null;
	} | null>(null);
	const bindDomFromRefs = useCallback(() => {
		const scroller = scrollerRef.current;
		const content = contentRef.current;
		const overlay = overlayRef.current;
		const prev = boundDomRef.current;
		if (
			prev &&
			prev.scroller === scroller &&
			prev.content === content &&
			prev.overlay === overlay
		) {
			return;
		}
		boundDomRef.current = {scroller, content, overlay};
		controller.bindDom({scroller, content, overlay});
	}, [controller, scrollerRef, contentRef, overlayRef]);

	useEffect(() => {
		bindDomFromRefs();
	});

	useEffect(() => {
		controller.setStreaming(streaming);
	}, [controller, streaming]);

	useEffect(() => {
		return () => controller.dispose();
	}, [controller]);

	const flushStuck = useCallback(() => {
		bindDomFromRefs();
		return controller.flush();
	}, [controller, bindDomFromRefs]);

	const requestStuck = useCallback(() => {
		flushStuck();
	}, [flushStuck]);

	const registerSticky = useCallback(
		(id: string, node: HTMLElement | null, editable: boolean) => {
			if (!node) {
				if (controller.unregisterShell(id)) {
					requestStuck();
				}
				return;
			}
			if (controller.registerShell(id, node, editable)) {
				requestStuck();
			}
		},
		[controller, requestStuck],
	);

	const beginStickyEdit = useCallback(
		(message: {id: string; text: string}) => {
			controller.bindDom({
				scroller: scrollerRef.current,
				content: contentRef.current,
				overlay: overlayRef.current,
			});
			return controller.beginEdit(message);
		},
		[controller, scrollerRef, contentRef, overlayRef],
	);

	const endStickyEdit = useCallback(() => {
		controller.endEdit();
		requestStuck();
	}, [controller, requestStuck]);

	const setEditingId = useCallback(
		(id: string | null) => {
			controller.setEditingId(id);
		},
		[controller],
	);

	const muteStickyLayoutSnap = useCallback(() => {
		controller.muteLayoutSnap();
	}, [controller]);

	return {
		controller,
		editPortalHost,
		flushStuck,
		requestStuck,
		registerSticky,
		beginStickyEdit,
		endStickyEdit,
		setEditingId,
		muteStickyLayoutSnap,
		isLayoutMuted: () => controller.isLayoutMuted(),
		phase: () => controller.getPhase(),
	};
}
