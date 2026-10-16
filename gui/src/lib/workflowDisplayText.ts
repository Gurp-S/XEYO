import {stripXmlToolCallsForDisplay} from './stripXmlToolCalls';

/** 流占位标记和原始工具标记不作为可读叙述。 */
export function workflowDisplayText(text: string): string {
	return stripXmlToolCallsForDisplay(text).replace(/[\u200b\ufeff]/g, '').trim();
}

export function previousWorkflowText(events: readonly {text: string}[], before: number): string {
	for (let index = before - 1; index >= 0; index--) {
		if (workflowDisplayText(events[index].text)) return events[index].text;
	}
	return '';
}
