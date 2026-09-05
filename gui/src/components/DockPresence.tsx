import type {ReactNode} from 'react';
import {usePresence} from '@/hooks/usePresence';
import {cn} from '@/lib/utils';

type Props = {
	open: boolean;
	smoothness: boolean;
	children: ReactNode;
};

/** Todo / 错误条进出：流畅开时高度瞬间，内容 opacity + translateY；关则硬切。 */
export function DockPresence({open, smoothness, children}: Props) {
	const {mounted, shown} = usePresence(open, smoothness ? 180 : 0);
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
