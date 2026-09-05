import {type HTMLAttributes, type ReactNode, type Ref} from 'react';
import {cn} from '@/lib/utils';

type PageShellProps = {
	/**
	 * 全宽信息面板（用量页）。false = 居中列表布局（扩展中心：
	 * max-w-3xl 居中 + xy-hover-scroll 滚动渐隐）。
	 * 两种形态的 DOM 与两面板重构前（2026-09-05 复用审计 ⑥ 之前）
	 * 逐类一致，勿随意增删类——视觉回归会直接被用户感知。
	 */
	wide?: boolean;
	/** 顶部工具条插槽（筛选器、tablist 等） */
	toolbar?: ReactNode;
	/** 工具条容器 ref（供外部做吸顶/尺寸测量） */
	toolbarRef?: Ref<HTMLDivElement>;
	className?: string;
	children?: ReactNode;
} & Omit<HTMLAttributes<HTMLDivElement>, 'className'>;

/**
 * 页面级面板外壳：工具条 + 可滚动内容区。
 * data-testid / aria-* 等属性透传到根节点。
 */
export function PageShell({
	wide,
	toolbar,
	toolbarRef,
	className,
	children,
	...rest
}: PageShellProps) {
	return (
		<div
			className={cn('xy-usage-page flex min-h-0 flex-1 flex-col', className)}
			{...rest}
		>
			{toolbar ? (
				<div
					ref={toolbarRef}
					className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line/40 px-4 py-2"
				>
					{toolbar}
				</div>
			) : null}
			<div
				className={cn(
					'relative min-h-0 flex-1 overflow-y-auto px-4 py-4',
					!wide && 'xy-hover-scroll',
				)}
			>
				{wide ? (
					children
				) : (
					<div className="mx-auto flex w-full max-w-3xl min-w-0 flex-col">
						{children}
					</div>
				)}
			</div>
		</div>
	);
}
