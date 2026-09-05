import {useState} from 'react';
import {ChevronDown} from 'lucide-react';

import {resolvePlan} from '@/lib/api';
import {usePendingPlanForActiveSession} from '@/hooks/usePendingForActiveSession';
import {useChatStore, type PendingPlanInfo} from '@/stores/chatStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {cn} from '@/lib/utils';
import {DockPresence} from './DockPresence';
import {PanelCollapse} from './PanelCollapse';

export function PlanDialog() {
	const pending = usePendingPlanForActiveSession();
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));

	return (
		<DockPresence open={Boolean(pending)} smoothness={smoothness}>
			{pending ? (
				<PlanCard key={pending.requestId} pending={pending} />
			) : null}
		</DockPresence>
	);
}

function PlanCard({pending}: {pending: PendingPlanInfo}) {
	const [expanded, setExpanded] = useState(true);

	const decide = (approved: boolean) => {
		useChatStore.getState().setPendingPlan?.(null);
		void resolvePlan(pending.requestId, approved);
	};

	return (
		<div
			className={cn('xy-panel-ask', expanded && 'is-expanded')}
			role="alertdialog"
			aria-label="Plan 确认"
		>
			<div
				className="xy-panel-ask-head"
				aria-expanded={expanded}
				onClick={() => setExpanded(v => !v)}
			>
				<span className="xy-panel-ask-caret" aria-hidden="true">
					<ChevronDown
						className={cn(
							'size-3.5 transition-transform duration-200 ease-out',
							!expanded && '-rotate-90',
						)}
					/>
				</span>
				<span className="xy-panel-ask-title">Plan</span>
				<span className="xy-panel-ask-count">等待确认执行</span>
				<span className="xy-panel-ask-dot" aria-hidden="true" />
			</div>

			<PanelCollapse open={expanded} className="xy-panel-ask-body">
				<div className="xy-panel-ask-cmd whitespace-pre-wrap">
					{pending.plan}
				</div>
				<div className="xy-panel-ask-actions">
					<button
						type="button"
						className="xy-panel-ask-reject"
						onClick={() => decide(false)}
					>
						拒绝
					</button>
					<button
						type="button"
						className="xy-panel-ask-allow"
						onClick={() => decide(true)}
					>
						允许执行
					</button>
				</div>
			</PanelCollapse>
		</div>
	);
}
