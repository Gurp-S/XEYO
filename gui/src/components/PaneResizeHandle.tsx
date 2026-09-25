import {useEffect, useRef, useState} from 'react';
import {cn} from '@/lib/utils';

const HOVER_DELAY_MS = 180;

type Props = {
	edge: 'left' | 'right';
	dragging: boolean;
	label: string;
	onMouseDown: (e: React.MouseEvent) => void;
	onKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
	value: number;
	minValue: number;
	maxValue: number;
};

/** 全高命中区 + 中段淡出圆角缝 + 悬停握把；避免全高直角竖线切开感。 */
export function PaneResizeHandle({
	edge,
	dragging,
	label,
	onMouseDown,
	onKeyDown,
	value,
	minValue,
	maxValue,
}: Props) {
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
			aria-valuemin={Math.round(minValue)}
			aria-valuemax={Math.round(maxValue)}
			aria-valuenow={Math.round(value)}
			aria-valuetext={`${Math.round(value)} 像素`}
			tabIndex={0}
			title="拖动或使用方向键调整宽度"
			onMouseDown={onMouseDown}
			onKeyDown={onKeyDown}
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
				edge === 'right' ? 'is-edge-right right-0' : 'is-edge-left left-0',
				lit && 'is-lit',
				dragging && 'is-dragging',
			)}
		>
			<span aria-hidden className="xy-pane-resize-seam" />
			<span
				aria-hidden
				className={cn(
					'xy-pane-resize-grip rounded-full transition-[height,width,background-color,opacity] duration-150 ease-out',
					'motion-reduce:transition-none',
					lit ? 'opacity-100' : 'opacity-0',
					dragging ? 'h-16 w-1.5 bg-accent/55' : 'h-12 w-1 bg-accent/35',
				)}
			/>
		</div>
	);
}
