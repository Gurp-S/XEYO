import {Fragment, memo} from 'react';
import {activityCaption, toolCallLabel, type RoundActivity} from '@/lib/roundActivity';
import {ActivityIcon} from './ActivityIcon';

type Props = {events: RoundActivity[]; activeId?: string; onSelect: (id: string) => void};

/** Prose and tool output updates do not change the trace's labels. */
export const WorkflowTrace = memo(function WorkflowTrace({events, activeId, onSelect}: Props) {
	return events.map((event, index) => <Fragment key={event.id}>
		{index > 0 && <span className="xy-round-arrow" aria-hidden>→</span>}
		<button aria-pressed={activeId === event.id} tabIndex={activeId === event.id ? 0 : -1}
			className={`${event.live ? 'is-live' : ''} ${event.error ? 'is-error' : ''}`}
			title={event.tool ? toolCallLabel(event.tool) : event.label}
			onClick={() => onSelect(event.id)} onKeyDown={key => {
				if (key.key !== 'ArrowLeft' && key.key !== 'ArrowRight') return;
				key.preventDefault();
				const nextIndex = index + (key.key === 'ArrowRight' ? 1 : -1);
				const next = events[nextIndex];
				if (next) {
					onSelect(next.id);
					key.currentTarget.parentElement?.querySelectorAll('button')[nextIndex]?.focus();
				}
			}}>
			<ActivityIcon event={event}/><span>{activityCaption(event)}</span>
			{event.error && <span className="xy-activity-error-dot" aria-label="失败"/>}
		</button>
	</Fragment>);
}, (prev, next) => prev.activeId === next.activeId && prev.onSelect === next.onSelect &&
	prev.events.length === next.events.length && prev.events.every((event, index) => {
		const other = next.events[index]!;
		return event.id === other.id && event.label === other.label && event.live === other.live &&
			event.error === other.error && event.tool?.name === other.tool?.name &&
			event.tool?.input === other.tool?.input && event.tool?.status === other.tool?.status;
	}));
