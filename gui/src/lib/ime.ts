/** 键盘事件属于正在进行的输入法组词时返回 true。 */
export function isImeComposing(
	event: Pick<KeyboardEvent, 'isComposing' | 'key' | 'keyCode'>,
): boolean {
	return event.isComposing || event.keyCode === 229 || event.key === 'Process';
}
