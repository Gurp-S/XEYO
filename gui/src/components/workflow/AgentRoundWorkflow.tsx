import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {useSignals} from '@preact/signals-react/runtime';
import {Check, ChevronRight, Clock3, Copy} from 'lucide-react';
import type {TranscriptBlock} from '@/lib/groupTranscript';
import {roundActivities, toolCallLabel} from '@/lib/roundActivity';
import {previousWorkflowText, workflowDisplayText} from '@/lib/workflowDisplayText';
import {workflowStreamVisible} from '@/lib/workflowStreamPresence';
import {WorkflowTrace} from './WorkflowTrace';
import {ActivityNavigator} from './ActivityNavigator';
import {streamingTextSignal} from '@/lib/streamSignal';
import {StreamingMarkdown} from '../StreamingMarkdown';
import {WorkflowStreamText} from './WorkflowStreamText';
import {toolStepMenuItems} from '@/lib/contextMenus';
import {showContextMenu} from '../ui/ContextMenu';
import {toast} from '@/lib/toast';
import {openPageView} from '@/lib/appNav';
import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';

export function AgentRoundWorkflow({blocks, settled, signalLive, status}: {
	blocks: TranscriptBlock[]; settled: boolean; signalLive: boolean; status: string;
}) {
	useSignals();
	const signalVisible = signalLive && !settled && workflowStreamVisible.value;
	const events = useMemo(() => roundActivities(blocks, settled, signalVisible), [blocks, settled, signalVisible]);
	const [selected, setSelected] = useState<string | null>(null);
	const [follow, setFollow] = useState(true);
	const [opened, setOpened] = useState<Record<string, boolean>>({});
	const trace = useRef<HTMLDivElement>(null);
	const event = events.find(e => e.id === (follow ? events.at(-1)?.id : selected)) ?? events.at(-1);
	const text = event && workflowDisplayText(event.text) ? event.text : previousWorkflowText(events, events.indexOf(event!));
	const usesSignal = Boolean(signalLive && !settled && event?.id.endsWith(':streaming'));
	const selectEvent = useCallback((id: string) => {setSelected(id); setFollow(false);}, []);
	useLayoutEffect(() => {
		if (follow && trace.current) trace.current.scrollLeft = trace.current.scrollWidth;
	}, [events.length, follow]);
	useLayoutEffect(() => {
		if (!follow && selected) {
			const index = events.findIndex(e => e.id === selected);
			const node = trace.current?.querySelectorAll('button')[index];
			if (node && trace.current) {
				const viewport = trace.current.getBoundingClientRect();
				const bounds = node.getBoundingClientRect();
				trace.current.scrollLeft += bounds.left - viewport.left - (viewport.width - bounds.width) / 2;
			}
		}
	}, [selected, follow]);
	useEffect(() => {
		const node = trace.current;
		if (!node) return;
		const wheel = (e: WheelEvent) => {
			if (e.ctrlKey || e.metaKey || node.scrollWidth <= node.clientWidth) return;
			const delta = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? node.clientWidth : 1);
			const before = node.scrollLeft;
			node.scrollLeft += delta;
			if (before !== node.scrollLeft) { e.preventDefault(); setSelected(event?.id ?? null); setFollow(false); }
		};
		node.addEventListener('wheel', wheel, {passive: false});
		return () => node.removeEventListener('wheel', wheel);
	}, [event?.id]);
	if (!events.length) return settled ? null : <section className="xy-round-workflow" aria-label="本轮 Agent 活动"><header><span><Clock3 size={14}/>{status || '等待模型响应'}</span></header></section>;
	const tool = event?.tool;
	return <section className="xy-round-workflow" aria-label="本轮 Agent 活动">
		<header><span>{settled ? <Check size={14} /> : <Clock3 size={14} />}{settled ? '本轮结束' : status || (event?.waiting ? '等待工具结果' : '进行中')}</span>
			<div className="xy-activity-controls">{!follow && <button onClick={() => setFollow(true)}>回到最新</button>}<ActivityNavigator events={events} activeId={event?.id} onSelect={selectEvent}/></div></header>
		<div className="xy-round-trace" ref={trace} aria-label="按发生顺序排列的活动" onPointerDown={e => {if (e.pointerType === 'touch') {setSelected(event?.id ?? null); setFollow(false);}}}>
			<WorkflowTrace events={events} activeId={event?.id} onSelect={selectEvent}/>
		</div>
		{event && <div className="xy-round-event" onContextMenu={e => {if(tool) showContextMenu(e, toolStepMenuItems({preview:toolCallLabel(tool),result:tool.result}), '工具调用');}}>
			{tool ? <><div className="xy-round-event-meta">{tool.name}<span>主 Agent</span></div>{text && <StreamingMarkdown text={text} final />}
			<details key={event.id} open={Boolean(opened[event.id])} onToggle={e => {const open = e.currentTarget.open; setOpened(prev => prev[event.id] === open ? prev : {...prev, [event.id]: open});}}>
				<summary><span>{toolCallLabel(tool)}</span><ChevronRight size={14} /></summary>
				{Boolean(opened[event.id]) && <div className="xy-round-tool-output"><h4>参数</h4><pre>{tool.input}</pre><h4>结果</h4><pre className={event.error ? 'text-danger' : ''}>{tool.result || (tool.waiting ? '等待工具结果…' : event.live ? '工具执行中…' : '工具未返回文本')}</pre>{event.error && tool.toolUseId && <button className="xy-dig-step-link" onClick={() => {const state = useChatStore.getState(); openPageView('diagnostics',{session:state.activeId ? activeBackendSessionId(state.historyById,state.activeId) : '',tool:tool.toolUseId!});}}>查看诊断</button>}</div>}
			</details></> : <WorkflowStreamText text={text} signalLive={usesSignal} live={event.live} />}
			<footer><button aria-label="复制这条记录" title="复制" onClick={() => {void navigator.clipboard.writeText(tool ? `${toolCallLabel(tool)}\n\n${tool.result}` : usesSignal ? streamingTextSignal.value || text : text).catch(() => toast.error('复制失败'));}}><Copy size={14} /></button></footer>
		</div>}
	</section>;
}
