export type EditUploadScope = {
	generation: number;
	sessionId: string | null;
	messageId: string | null;
};

/** Upload completions may update the editor only while their original edit is current. */
export function isCurrentEditUpload(
	captured: EditUploadScope,
	current: EditUploadScope,
): boolean {
	return (
		captured.generation === current.generation &&
		captured.sessionId !== null &&
		captured.sessionId === current.sessionId &&
		captured.messageId !== null &&
		captured.messageId === current.messageId
	);
}
