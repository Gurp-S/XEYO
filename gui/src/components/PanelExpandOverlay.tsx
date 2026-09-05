import {useEffect, type ReactNode} from 'react';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

/**
 * 通用「面板放大」容器：把宿主提供的 header + body 渲染进一个覆盖**内容区**
 * （聊天列 + 工作区）的高层遮罩，而非整个窗口——从而最多盖住聊天界面，
 * 不遮蔽左侧侧栏与标题栏。宿主复用其自身 header（内含 Maximize2/Minimize2
 * 切换按钮与关闭按钮），与 FilePreview 的放大形态保持一致。
 *
 * 受控组件：open 由宿主状态驱动；onClose 于用户按 Esc 时调用。
 * 打开期间锁定 body 滚动，并经 escStack 响应 Esc 退出。
 */
export function PanelExpandOverlay({
	open,
	onClose,
	children,
}: {
	open: boolean;
	onClose: () => void;
	children: ReactNode;
}) {
	useEffect(() => {
		if (!open) {
			return;
		}
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		pushEscLayer('panel-expand', onClose);
		return () => {
			document.body.style.overflow = prev;
			popEscLayer('panel-expand');
		};
	}, [open, onClose]);

	if (!open) {
		return null;
	}
	return (
		<div
			className="absolute inset-0 z-[80] flex flex-col overflow-hidden bg-paper"
			aria-label="放大面板"
		>
			{children}
		</div>
	);
}
