import type {ReactNode} from 'react';
import {cn} from '@/lib/utils';

/**
 * 页面视图（用量 / 扩展中心）挂载壳（2026-09-05 复用审计 ③）：
 * ChatPage 内两段复制粘贴的 absolute 覆盖层 + 淡入淡出结构收敛于此。
 * `active` 来自路由派生；`mounted` 来自 usePresence（退场动画期间保持挂载）。
 */
export function PageViewPane({
	active,
	mounted,
	children,
}: {
	active: boolean;
	mounted: boolean;
	children: ReactNode;
}) {
	if (!active && !mounted) {
		return null;
	}
	return (
		<div
			className={cn(
				'absolute inset-0 flex min-h-0 min-w-0 flex-col transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none',
				active
					? 'pointer-events-auto translate-y-0 opacity-100'
					: 'pointer-events-none -translate-y-1 opacity-0',
			)}
			aria-hidden={!active}
		>
			{children}
		</div>
	);
}
