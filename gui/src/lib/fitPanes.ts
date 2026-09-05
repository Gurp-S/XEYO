/** 窗口剩余给侧栏/预览/文件树的空间：先留对话 min，再按偏好宽度比例收缩。 */
export function shrinkOpenPanes(
	container: number,
	chatMin: number,
	preferred: number[],
): number[] {
	const room = Math.max(0, container - chatMin);
	const sum = preferred.reduce((a, b) => a + b, 0);
	if (sum <= room) {
		return preferred;
	}
	if (sum <= 0) {
		return preferred.map(() => 0);
	}
	const scale = room / sum;
	return preferred.map(w => Math.max(0, w * scale));
}
