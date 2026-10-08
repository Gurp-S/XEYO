/** Preserve typing done while the submission was awaiting its receipt. */
export function restoreFailedDraft(current: string, submitted: string): string {
	return current || submitted;
}
