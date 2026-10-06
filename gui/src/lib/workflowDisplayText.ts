import {stripXmlToolCallsForDisplay} from './stripXmlToolCalls';

/** The stream sentinel and raw tool markup are not readable narration. */
export function workflowDisplayText(text: string): string {
	return stripXmlToolCallsForDisplay(text).replace(/[\u200b\ufeff]/g, '').trim();
}

export function previousWorkflowText(events: readonly {text: string}[], before: number): string {
	for (let index = before - 1; index >= 0; index--) {
		if (workflowDisplayText(events[index].text)) return events[index].text;
	}
	return '';
}
