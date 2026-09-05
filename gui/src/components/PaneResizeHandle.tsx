import {useEffect, useRef, useState} from 'react';
import {cn} from '@/lib/utils';

const HOVER_DELAY_MS = 180;

type Props = {
	edge: 'left' | 'right';
	dragging: boolean;
	label: string;
	onMouseDown: (e: React.MouseEvent) => void;
};

/** 全高命中区 + 中段淡出圆角缝 + 悬停握把；避免全高直角竖线切开感。 */
export function PaneResizeHandle({edge, dragging, label, onMouseDown}: Props) {
	const [hot, setHot] = useState(false);
	const timer = useRef(0);

	useEffect(() => {
		return () => {
			if (timer.current) {
				window.clearTimeout(timer.current);
			}
		};
	}, []);

	const lit = hot || dragging;

	return (
		<div
			role="separator"
			aria-orientation="vertical"
			aria-label={label}
			title="拖动调整宽度"
			onMouseDown={onMouseDown}
			onMouseEnter={() => {
				if (timer.current) {
					window.clearTimeout(timer.current);
				}
				timer.current = window.setTimeout(() => {
					setHot(true);
					timer.current = 0;
				}, HOVER_DELAY_MS);
			}}
			onMouseLeave={() => {
				if (timer.current) {
					window.clearTimeout(timer.current);
					timer.current = 0;
				}
				setHot(false);
			}}
			className={cn(
				'xy-pane-resize-handle absolute top-0 z-20 h-full w-3 cursor-col-resize',
				lit && 'is-lit',
				dragging && 'is-dragging',
				edge === 'right'
					? 'right-0 translate-x-1/2'
					: 'left-0 -translate-x-1/2',
			)}
		>
			<span aria-hidden className="xy-pane-resize-seam" />
			<span
				aria-hidden
				className={cn(
					'xy-pane-resize-grip pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2',
					'rounded-full transition-[height,width,background-color,opacity] duration-150 ease-out',
					'motion-reduce:transition-none',
					lit ? 'opacity-100' : 'opacity-0',
					dragging ? 'h-16 w-1.5 bg-accent/55' : 'h-12 w-1 bg-accent/35',
				)}
			/>
		</div>
	);
}
