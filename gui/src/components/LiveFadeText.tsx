import {useRef, type ElementType} from 'react';
import {fadeWindowForStep, fadeOpacityForOffset} from '@/lib/fadeRamp';

const styleCache = new Map<string, {opacity: number}>();

export {fadeWindowForStep} from '@/lib/fadeRamp';

/** fromEnd=0 为最末一字（最淡）；fromEnd=window-1 接近实心。 */
export function fadeStyleForOffset(
	fromEnd: number,
	window: number,
): {opacity: number} {
	const key = `${fromEnd}/${window}`;
	let style = styleCache.get(key);
	if (!style) {
		style = {opacity: fadeOpacityForOffset(fromEnd, window)};
		styleCache.set(key, style);
	}
	return style;
}

type Props = {
	text: string;
	className?: string;
	as?: ElementType;
};

/**
 * 实心前缀文本节点 + 末尾 N 码点透明度 span。
 * 透明度不改布局、不产生裁剪层，跨行也沿阅读方向渐变。
 */
export function LiveFadeText({text, className, as: Tag = 'span'}: Props) {
	const prevLenRef = useRef(0);
	const points = Array.from(text);
	const step = Math.max(1, points.length - prevLenRef.current);
	prevLenRef.current = points.length;
	const window = fadeWindowForStep(step);
	const fadeStart = Math.max(0, points.length - window);

	return (
		<Tag className={className}>
			{fadeStart > 0 ? points.slice(0, fadeStart).join('') : null}
			{points.slice(fadeStart).map((ch, offset) => {
				const i = fadeStart + offset;
				const fromEnd = points.length - 1 - i;
				return (
					<span
						key={i}
						className="xy-char"
						style={fadeStyleForOffset(fromEnd, window)}
					>
						{ch}
					</span>
				);
			})}
		</Tag>
	);
}
