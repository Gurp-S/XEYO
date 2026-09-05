import {
	useLayoutEffect,
	useRef,
	type ReactNode,
} from 'react';
import {cn} from '@/lib/utils';

const EASE = 'height 0.22s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.16s ease';
/** 超过此高度用短切/淡入，避免长列表每帧 layout（替代 grid 0fr→1fr） */
const LONG_PX = 280;

/**
 * 用 height 实测做展开/收起；长内容直接切，短内容保留过渡。
 */
export function ExpandPanel({
	open,
	children,
	className,
	innerClassName,
}: {
	open: boolean;
	children: ReactNode;
	className?: string;
	innerClassName?: string;
}) {
	const outerRef = useRef<HTMLDivElement>(null);
	const innerRef = useRef<HTMLDivElement>(null);
	const prevOpen = useRef<boolean | null>(null);

	useLayoutEffect(() => {
		const outer = outerRef.current;
		const inner = innerRef.current;
		if (!outer || !inner) {
			return;
		}

		const reduce =
			typeof document !== 'undefined' &&
			document.documentElement.getAttribute('data-smoothness') === 'off';

		const was = prevOpen.current;
		prevOpen.current = open;

		// 首次挂载：对齐目标态，不播动画
		if (was === null) {
			outer.style.transition = 'none';
			outer.style.willChange = 'auto';
			outer.style.opacity = open ? '1' : '0';
			outer.style.height = open ? 'auto' : '0px';
			outer.style.overflow = open ? 'visible' : 'hidden';
			return;
		}

		if (was === open) {
			return;
		}

		const to = open ? inner.scrollHeight : 0;
		const from = was
			? outer.getBoundingClientRect().height || inner.scrollHeight
			: 0;
		const long = Math.max(from, to) > LONG_PX;

		if (reduce || long) {
			outer.style.transition = long && !reduce ? 'opacity 0.12s ease' : 'none';
			outer.style.willChange = 'auto';
			outer.style.overflow = 'hidden';
			outer.style.height = open ? `${to || inner.scrollHeight}px` : '0px';
			outer.style.opacity = open ? '1' : '0';
			if (open) {
				requestAnimationFrame(() => {
					if (outerRef.current === outer && prevOpen.current === true) {
						outer.style.height = 'auto';
						outer.style.overflow = 'visible';
						outer.style.transition = '';
					}
				});
			} else {
				outer.style.transition = '';
			}
			return;
		}

		outer.style.overflow = 'hidden';
		outer.style.willChange = 'height, opacity';
		outer.style.transition = 'none';
		outer.style.height = `${from}px`;
		outer.style.opacity = was ? '1' : '0';
		void outer.offsetHeight;
		outer.style.transition = EASE;
		outer.style.height = `${to}px`;
		outer.style.opacity = open ? '1' : '0';

		const onEnd = (e: TransitionEvent) => {
			if (e.target !== outer || e.propertyName !== 'height') {
				return;
			}
			if (open) {
				outer.style.height = 'auto';
				outer.style.overflow = 'visible';
			}
			outer.style.willChange = 'auto';
			outer.style.transition = '';
		};
		outer.addEventListener('transitionend', onEnd);
		return () => {
			outer.removeEventListener('transitionend', onEnd);
		};
	}, [open]);

	return (
		<div ref={outerRef} className={cn('xy-expand-panel', className)}>
			<div
				ref={innerRef}
				className={cn('xy-expand-panel-inner', innerClassName)}
			>
				{children}
			</div>
		</div>
	);
}
