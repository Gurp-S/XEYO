import type {ReactNode} from 'react';
import {cn} from '@/lib/utils';

type Props = {
	open: boolean;
	children: ReactNode;
	/** 应用到裁切层内侧的内容壳（如 xy-panel-ask-body），勿放 overflow。 */
	className?: string;
};

/**
 * Ask / Todo / 审批面板主体：grid 高度过渡。
 * 外层 overflow:hidden 裁切；padding / 滚动只放在内层内容壳上。
 */
export function PanelCollapse({open, children, className}: Props) {
	return (
		<div className={cn('xy-panel-collapse', open && 'open')}>
			<div className="xy-panel-collapse-inner">
				{className ? (
					<div className={className}>{children}</div>
				) : (
					children
				)}
			</div>
		</div>
	);
}
