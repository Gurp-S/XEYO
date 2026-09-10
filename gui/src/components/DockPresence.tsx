import {useMemo, type ReactNode} from 'react';
import {usePresence} from '@/hooks/usePresence';
import {cssDurationMs, presenceExitMs} from '@/lib/motionDuration';
import {cn} from '@/lib/utils';

type Props = {
	open: boolean;
	smoothness: boolean;
	children: ReactNode;
};

/** Todo / 错误条进出：流畅开时高度瞬间，内容 opacity + translateY；关则硬切。 */
export function DockPresence({open, smoothness, children}: Props) {
	// 退出延迟由 .xy-dock-presence 的 grid-template-rows 过渡时长推导。
	// 原先写死 180ms < CSS 的 200ms，收起末帧会被截断（面板越高越明显）。
	const exitMs = useMemo(() => presenceExitMs(cssDurationMs('base')), []);
	const {mounted, shown} = usePresence(open, smoothness ? exitMs : 0);
	if (!smoothness) {
		if (!open) {
			return null;
		}
		return <>{children}</>;
	}
	if (!mounted) {
		return null;
	}
	return (
		<div className="xy-dock-presence">
			<div className={cn('xy-dock-presence-inner', shown && 'open')}>
				{children}
			</div>
		</div>
	);
}
