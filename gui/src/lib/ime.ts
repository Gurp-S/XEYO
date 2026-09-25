/** True while a keyboard event belongs to an active IME composition. */
export function isImeComposing(
	event: Pick<KeyboardEvent, 'isComposing' | 'key' | 'keyCode'>,
): boolean {
	return event.isComposing || event.keyCode === 229 || event.key === 'Process';
}
