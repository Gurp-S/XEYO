/**
 * 把当前看到的用量数据导成 JSON（用量页与 A3 网页报告的「导出 JSON」对齐）。
 *
 * 走 Blob + `<a download>`：与诊断中心导出 Markdown 同一手法（桌面壳的 WebView2 支持），
 * 不引入新依赖、不写磁盘、不碰 Tauri 文件插件的权限 scope。
 */
export function usageExportFilename(at: string): string {
	const m = /^(\d{4}-\d{2}-\d{2})/.exec(at || '');
	return `xeyo-usage-${m ? m[1] : 'export'}.json`;
}

export function downloadUsageJson(payload: unknown, generatedAt: string): string {
	const blob = new Blob([JSON.stringify(payload, null, 2)], {
		type: 'application/json;charset=utf-8',
	});
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	const name = usageExportFilename(generatedAt);
	a.href = url;
	a.download = name;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	window.setTimeout(() => URL.revokeObjectURL(url), 2000);
	return name;
}
