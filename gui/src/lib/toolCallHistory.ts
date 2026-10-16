import {groupTranscript, type TurnItem} from '@/lib/groupTranscript';
function commandDisplayText(input: string): string {
	try {
		const parsed = JSON.parse(input) as unknown;
		if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
			const command = (parsed as Record<string, unknown>).command;
			if (typeof command === 'string') {
				return command;
			}
		}
	} catch {
		/* 非 JSON，走下方转义还原 */
	}
	return input.replace(/\\r\\n|\\n/g, '\n').replace(/\\t/g, '\t');
}

export function collectCalls(messages: ChatMessageLike[]): Array<{id: string; name: string; input: string; display: string}> {
	try {
		const blocks = groupTranscript(messages);
		const items = blocks.flatMap(b => (b.kind === 'turn' ? b.items : []));
		return items
			.filter((it): it is Extract<TurnItem, {kind: 'tool'}> => it.kind === 'tool')
			.filter(it => it.tool.name && it.tool.input)
			.map(it => ({id:it.tool.id, name: it.tool.name, input: it.tool.input, display: it.tool.name==='Bash' ? commandDisplayText(it.tool.input) : it.tool.input}));
	} catch {
		return [];
	}
}

type ChatMessageLike = Parameters<typeof groupTranscript>[0][number];



export function callSummary(name: string, input: string, display: string): string {
 if (name === 'Bash') return display.split('\n')[0] || '(空命令)';
 try {
  const value = JSON.parse(input);
  for (const key of ['query','pattern','file_path','path','url','description','prompt']) {
   if (typeof value?.[key] === 'string' && value[key]) return value[key].split('\n')[0];
  }
 } catch { /* Plain text tool input remains readable. */ }
 return display.split('\n')[0] || '(无参数)';
}
