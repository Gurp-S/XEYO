import type {TranscriptBlock, ToolView} from './groupTranscript';
import {finalRoundProseMessageIds, categorize} from './toolActivity';
import {workflowDisplayText} from './workflowDisplayText';

export type RoundActivity = {
	id: string;
	label: string;
	text: string;
	live: boolean;
	error?: boolean;
	waiting?: boolean;
	tool?: ToolView;
};

/** All received events, in transcript order; never a planned sequence of stages. */
export function roundActivities(blocks: TranscriptBlock[], settled: boolean, signalLive = false): RoundActivity[] {
	const turns = blocks.filter(b => b.kind === 'turn');
	const finalIds = settled ? finalRoundProseMessageIds(turns) : new Set<string>();
	const events: RoundActivity[] = [];
	let narration = '';
	for (const block of turns) {
		for (const item of block.items) {
			if (item.kind === 'assistant') {
				if (!workflowDisplayText(item.message.text)) continue;
				narration = item.message.text;
				if (finalIds.has(item.message.id)) continue;
				events.push({id: item.message.id, label: item.message.isThought ? '思考' : '回复', text: item.message.text, live: false});
			} else {
				const tool = item.tool;
				if (tool.reasoningBefore && workflowDisplayText(tool.reasoningBefore)) {
					if (narration !== tool.reasoningBefore) events.push({id: `${tool.id}:thought`, label: '思考', text: tool.reasoningBefore, live: false});
					narration = tool.reasoningBefore;
				}
				const label = ({read: '读取', write: '修改', edit: '修改', search: '搜索', run: '命令', lint: '检查', todo: '任务'} as Record<string, string>)[categorize(tool.name)] ?? tool.name;
				events.push({id: tool.id, label, text: narration, live: tool.status === 'running', error: tool.status === 'error', waiting: tool.waiting, tool});
			}
		}
		if (block.thinking && workflowDisplayText(block.thinking)) events.push({id: `${block.id}:thinking`, label: '思考', text: block.thinking, live: block.active});
		if (block.streaming && (workflowDisplayText(block.streaming) || (signalLive && block.streaming === '\u200b'))) events.push({id: `${block.id}:streaming`, label: '回复', text: block.streaming, live: block.active});
	}
	return events;
}

export function toolCallLabel(tool: ToolView): string {
	let args: Record<string, unknown> = {};
	try { args = JSON.parse(tool.input) as Record<string, unknown>; } catch { /* plain arguments */ }
	const detail = args?.command ?? args?.file_path ?? args?.path ?? args?.pattern ?? tool.input;
	return `${tool.name} ${typeof detail === 'string' ? detail : ''}`.trim();
}

/** Compact action captions; complete arguments stay available in the detail. */
export function activityCaption(event: RoundActivity): string {
	if (!event.tool) return event.label;
	const tool = event.tool;
	let args: Record<string, unknown> = {};
	try { const parsed: unknown = JSON.parse(tool.input); if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) args = parsed as Record<string, unknown>; } catch { /* plain arguments */ }
	const cat = categorize(tool.name);
	const path = args.file_path ?? args.path ?? args.filePath ?? args.notebook_path;
	const detail = typeof path === 'string' ? path.replace(/\\/g, '/').split('/').at(-1) : cat === 'run' ? args.command ?? tool.input : cat === 'search' ? args.pattern ?? args.query : undefined;
	const verb = cat === 'run' ? '执行' : event.label;
	const done = tool.status === 'done' ? '了' : '';
	const short = typeof detail === 'string' ? detail.replace(/\s+/g,' ').trim() : '';
	return `${verb}${done}${short ? `(${Array.from(short).slice(0,36).join('')}${Array.from(short).length > 36 ? '…' : ''})` : ''}`;
}
