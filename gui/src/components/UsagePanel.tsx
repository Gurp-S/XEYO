import {A3SnapshotPanel} from '@/components/A3SnapshotPanel';
import {PageShell} from '@/components/PageShell';

/**
 * 用量视图以定时生成的 A3 日报为主要内容。
 * 保留旧余额格式化函数的导出，以兼容现有调用方。
 */
export function fmtBalance(raw: string, currency?: string): string {
	const value = String(raw ?? '').trim();
	if (!value || !Number.isFinite(Number(value))) {
		return '—';
	}
	const unit = (currency || 'CNY').toUpperCase() === 'USD' ? '$' : '¥';
	return unit + value;
}

type Props = {
	active?: boolean;
};

export function UsagePanel({active = true}: Props) {
	return (
		<PageShell wide>
			<div className="mx-auto w-full max-w-[1400px]">
				<A3SnapshotPanel active={active} />
			</div>
		</PageShell>
	);
}
