/** 检测 Tauri 桌面壳。 */
export function isTauri(): boolean {
	return (
		typeof window !== 'undefined' &&
		('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
	);
}
