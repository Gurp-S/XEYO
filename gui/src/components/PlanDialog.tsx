import {useState} from 'react';
import {ChevronDown} from 'lucide-react';

import {resolveFailureText, resolvePlan} from '@/lib/api';
import {toast} from '@/lib/toast';
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

	const [submitting, setSubmitting] = useState(false);

	const decide = async (approved: boolean) => {
		if (submitting) {
			return;
		}
		setSubmitting(true);
		// 原先是"先清面板、再 void resolvePlan"：裁决没送达也照样收面板，
		// 引擎就在无人应答地等这个计划，界面上已经没有能答它的入口了。
		const receipt = await resolvePlan(pending.requestId, approved);
		setSubmitting(false);
		if (receipt.ok || receipt.reason === 'already_resolved') {
			useChatStore.getState().setPendingPlan?.(null);
		}
		if (!receipt.ok) {
			const notice = resolveFailureText(receipt);
			toast[notice.tone](notice.text);
		}
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
						onClick={() => void decide(false)}
					>
						拒绝
					</button>
					<button
						type="button"
						className="xy-panel-ask-allow"
						onClick={() => void decide(true)}
					>
						允许执行
					</button>
				</div>
			</PanelCollapse>
		</div>
	);
}
