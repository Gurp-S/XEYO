import {useSignals} from '@preact/signals-react/runtime';
import {streamingTextSignal} from '@/lib/streamSignal';
import {workflowDisplayText} from '@/lib/workflowDisplayText';
import {StreamingMarkdown} from '../StreamingMarkdown';

/** Keep token notifications below the event navigator and tool trace. */
export function WorkflowStreamText({text, signalLive, live}: {
	text: string; signalLive: boolean; live: boolean;
}) {
	useSignals();
	const raw = signalLive ? streamingTextSignal.value : '';
	const value = workflowDisplayText(raw) ? raw : '';
	return <StreamingMarkdown text={value || text} final={!live || (signalLive && !value)} />;
}
