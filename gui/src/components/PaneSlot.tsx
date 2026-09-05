import type {ReactNode, Ref} from 'react';
import {cn} from '@/lib/utils';

type Props = {
	open: boolean;
	mounted: boolean;
	shown: boolean;
	width: number;
	smoothness: boolean;
	dragging: boolean;
	side: 'left' | 'right';
	paneRef: Ref<HTMLElement | null>;
	as?: 'aside' | 'section';
	/** 流畅时保持子树挂载，避免再次点开时整栏重挂卡一下。 */
	keepAlive?: boolean;
	/** 功能界面间切换：禁用本帧过渡，直接硬切到目标状态。 */
	instant?: boolean;
	className?: string;
	children: ReactNode;
	onMouseEnter?: () => void;
	onMouseLeave?: () => void;
};

/**
 * 面板槽只负责一次性的布局占位，禁止对 width 做逐帧过渡。
 * 逐帧 width 会让聊天区、编辑器和所有 flex 子树反复重排；面板本身改用
 * 固定宽度的绝对定位内容配合 transform，动画期间只发生合成层位移。
 */
export function PaneSlot({
	open,
	mounted,
	shown,
	width,
	smoothness,
	side,
	dragging,
	paneRef,
	as: Tag = 'aside',
	keepAlive = false,
	instant = false,
	className,
	children,
	onMouseEnter,
	onMouseLeave,
}: Props) {
	if (!smoothness) {
		if (!mounted) {
			return null;
		}
		return (
			<Tag
				ref={paneRef as never}
				className={cn(
					'xy-sidebar relative flex h-full min-h-0 min-w-0 shrink flex-col overflow-hidden isolate',
					dragging && 'xy-pane-dragging xy-sidebar-dragging',
					instant && 'xy-pane-instant',
					className,
				)}
				style={{width: shown ? width : 0, flexBasis: shown ? width : 0}}
				aria-hidden={!shown}
				onMouseEnter={onMouseEnter}
				onMouseLeave={onMouseLeave}
			>
				{children}
			</Tag>
		);
	}

	const showChildren = keepAlive || mounted || open;
		// mounted 负责保留退出子树；open 负责立即启动槽位宽度过渡，
		// 这样 pane 的反向 transform 和聊天区的横向移动在同一帧开始。
		const slot = open ? width : 0;
	const hiddenTransform = side === 'left' ? 'translateX(-100%)' : 'translateX(100%)';

	return (
		<div
			ref={paneRef as never}
			className={cn(
				'xy-pane-slot relative h-full min-h-0 min-w-0 shrink overflow-hidden isolate',
				dragging && 'xy-pane-dragging xy-sidebar-dragging',
				instant && 'xy-pane-instant',
			)}
			style={{width: slot, flexBasis: slot}}
			aria-hidden={!open}
			onMouseEnter={onMouseEnter}
			onMouseLeave={onMouseLeave}
		>
			{showChildren ? (
				<Tag
					className={cn(
						'xy-sidebar xy-pane-slide absolute inset-y-0 flex min-h-0 min-w-0 flex-col overflow-hidden',
						!shown && 'pointer-events-none',
						className,
					)}
					style={{
						width,
						left: side === 'left' ? 0 : undefined,
						right: side === 'right' ? 0 : undefined,
						transform: shown ? 'translateX(0)' : hiddenTransform,
					}}
				>
					{children}
				</Tag>
			) : null}
		</div>
	);
}
