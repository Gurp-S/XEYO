import {type HTMLAttributes, type ReactNode, type Ref} from 'react';
import {cn} from '@/lib/utils';

type PageShellProps = {
	/** 宽幅布局（用量/扩展等信息密度高的面板） */
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
			className={cn(
				'flex min-h-0 flex-1 flex-col',
				className,
			)}
			{...rest}
		>
			{toolbar ? (
				<div ref={toolbarRef} className="shrink-0 px-4 pt-3 pb-2">
					{toolbar}
				</div>
			) : null}
			<div className="relative min-h-0 flex-1 overflow-y-auto px-4 pb-6">
				<div className={cn('mx-auto w-full', wide ? 'max-w-[1600px]' : 'max-w-5xl')}>
					{children}
				</div>
			</div>
		</div>
	);
}
