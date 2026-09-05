import {ChevronRight} from 'lucide-react';
import {cn} from '@/lib/utils';

/** 活动行折叠箭头：图标而非 `>` 字符，贴在文案右侧。 */
export function SplitChevron({
	open = false,
	className,
}: {
	open?: boolean;
	className?: string;
}) {
	return (
		<ChevronRight
			className={cn('xy-split-chevron', open && 'is-open', className)}
			aria-hidden
			size={14}
			strokeWidth={2}
		/>
	);
}
