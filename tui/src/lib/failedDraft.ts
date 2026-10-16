/** 保留等待提交回执期间用户新输入的内容。 */
export function restoreFailedDraft(current: string, submitted: string): string {
	return current || submitted;
}
