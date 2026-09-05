import {
	createContext,
	useCallback,
	useEffect,
	useMemo,
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
	/** 与 MessageList stickyLayoutMuteRef 对齐 */
	onLayoutMute?: () => void;
}) {
	const {
		messagesRef,
		scrollerRef,
		contentRef,
		overlayRef,
		streaming,
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

	useEffect(() => {
		controller.bindDom({
			scroller: scrollerRef.current,
			content: contentRef.current,
			overlay: overlayRef.current,
		});
	});

	useEffect(() => {
		controller.setStreaming(streaming);
	}, [controller, streaming]);

	useEffect(() => {
		return () => controller.dispose();
	}, [controller]);

	const flushStuck = useCallback(() => {
		controller.bindDom({
			scroller: scrollerRef.current,
			content: contentRef.current,
			overlay: overlayRef.current,
		});
		return controller.flush();
	}, [controller, scrollerRef, contentRef, overlayRef]);

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
