import {A3SnapshotPanel} from '@/components/A3SnapshotPanel';
import {PageShell} from '@/components/PageShell';

/**
 * Usage view now presents the scheduled A3 daily report as its primary surface.
 * Keep the legacy balance formatter exported for compatible callers.
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
