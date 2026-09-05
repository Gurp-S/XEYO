import type {CSSProperties, ReactNode} from 'react';
import {useLayoutEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {
	Bold,
	CirclePlay,
	Code,
	Italic,
	Link,
	List,
	ListOrdered,
	MessageCircle,
	Quote,
	SquareCode,
	Strikethrough,
	Underline,
} from 'lucide-react';
import type {MdFormatKind} from '@/lib/mdFormat';
import {cn} from '@/lib/utils';

type Props = {
	variant: 'markdown' | 'code';
	rect: DOMRect;
	bound: DOMRect;
	modLabel: string;
	onAskAgent: () => void;
	onAskSide: () => void;
	onFormat?: (kind: MdFormatKind) => void;
};

const btn =
	'inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-white/80 hover:bg-white/10 hover:text-white';

function ToolBtn({
	title,
	onClick,
	children,
}: {
	title: string;
	onClick: () => void;
	children: ReactNode;
}) {
	return (
		<button
			type="button"
				aria-label={title}
				className={btn}
				onClick={onClick}
		>
			{children}
		</button>
	);
}

function clampPos(rect: DOMRect, bound: DOMRect, w: number, h: number) {
	const gap = 8;
	const minL = bound.left + 6;
	const maxL = bound.right - w - 6;
	const center = rect.left + rect.width / 2;
	const left =
		maxL < minL
			? bound.left + Math.max(0, (bound.width - w) / 2)
			: Math.min(maxL, Math.max(minL, center - w / 2));
	let top = rect.top - h - gap;
	if (top < bound.top + 4) {
		top = Math.min(rect.bottom + gap, bound.bottom - h - 4);
	}
	return {top, left};
}

export function SelectionToolbar({
	variant,
	rect,
	bound,
	modLabel,
	onAskAgent,
	onAskSide,
	onFormat,
}: Props) {
	const ref = useRef<HTMLDivElement>(null);
	const [box, setBox] = useState({w: variant === 'markdown' ? 420 : 268, h: 36});

	useLayoutEffect(() => {
		const el = ref.current;
		if (!el) {
			return;
		}
		const r = el.getBoundingClientRect();
		if (Math.abs(r.width - box.w) > 1 || Math.abs(r.height - box.h) > 1) {
			setBox({w: r.width, h: r.height});
		}
	}, [variant, box.h, box.w, rect, bound]);

	const {top, left} = clampPos(rect, bound, box.w, box.h);
	const style: CSSProperties = {
		position: 'fixed',
		top,
		left,
		zIndex: 200,
	};

	return createPortal(
		<div
			ref={ref}
			role="toolbar"
			aria-label={variant === 'markdown' ? 'Markdown 选区工具' : '代码选区工具'}
			className={cn(
				'xy-no-drag flex w-max shrink-0 items-center gap-0.5 whitespace-nowrap border border-white/10 bg-[#2c3036] text-white shadow-[0_8px_28px_rgb(0_0_0/0.28)]',
				variant === 'markdown' ? 'rounded-full px-1.5 py-1' : 'rounded-lg px-1 py-1',
			)}
			style={style}
			onMouseDown={e => e.preventDefault()}
		>
			{variant === 'code' ? (
				<>
					<button
						type="button"
						className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[12px] text-white/90 hover:bg-white/10"
						onClick={onAskAgent}
					>
						Add to Chat
						<span className="font-mono text-[10px] text-white/40">
							{modLabel} L
						</span>
					</button>
					<button
						type="button"
						className="inline-flex h-7 shrink-0 items-center whitespace-nowrap rounded-md px-2.5 text-[12px] text-white/90 hover:bg-white/10"
						onClick={onAskSide}
					>
						Add to Side Chat
					</button>
				</>
			) : (
				<>
					<ToolBtn title="Ask Agent" onClick={onAskAgent}>
						<CirclePlay className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<ToolBtn title="Ask Side Chat" onClick={onAskSide}>
						<MessageCircle className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<span className="mx-0.5 h-4 w-px shrink-0 bg-white/15" />
					<ToolBtn title="加粗" onClick={() => onFormat?.('bold')}>
						<Bold className="h-3.5 w-3.5" strokeWidth={2.2} />
					</ToolBtn>
					<ToolBtn title="斜体" onClick={() => onFormat?.('italic')}>
						<Italic className="h-3.5 w-3.5" strokeWidth={2.2} />
					</ToolBtn>
					<ToolBtn title="下划线" onClick={() => onFormat?.('underline')}>
						<Underline className="h-3.5 w-3.5" strokeWidth={2.2} />
					</ToolBtn>
					<ToolBtn title="删除线" onClick={() => onFormat?.('strike')}>
						<Strikethrough className="h-3.5 w-3.5" strokeWidth={2.2} />
					</ToolBtn>
					<ToolBtn title="链接" onClick={() => onFormat?.('link')}>
						<Link className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<ToolBtn title="有序列表" onClick={() => onFormat?.('ol')}>
						<ListOrdered className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<ToolBtn title="无序列表" onClick={() => onFormat?.('ul')}>
						<List className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<ToolBtn title="引用" onClick={() => onFormat?.('quote')}>
						<Quote className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<ToolBtn title="行内代码" onClick={() => onFormat?.('code')}>
						<Code className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
					<ToolBtn title="代码块" onClick={() => onFormat?.('codeblock')}>
						<SquareCode className="h-3.5 w-3.5" strokeWidth={1.75} />
					</ToolBtn>
				</>
			)}
		</div>,
		document.body,
	);
}
