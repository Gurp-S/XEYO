import {useSignals} from '@preact/signals-react/runtime';
import {streamingTextSignal} from '@/lib/streamSignal';
import {workflowDisplayText} from '@/lib/workflowDisplayText';
import {StreamingMarkdown} from '../StreamingMarkdown';

/** 将 token 更新订阅放在事件导航和工具轨迹组件的下层。 */
export function WorkflowStreamText({text, signalLive, live}: {
	text: string; signalLive: boolean; live: boolean;
}) {
	useSignals();
	const raw = signalLive ? streamingTextSignal.value : '';
	const value = workflowDisplayText(raw) ? raw : '';
	return <StreamingMarkdown text={value || text} final={!live || (signalLive && !value)} />;
}
