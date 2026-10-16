export type EditUploadScope = {
	generation: number;
	sessionId: string | null;
	messageId: string | null;
};

/** 上传完成后，仅在原编辑会话仍有效时更新编辑器。 */
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
