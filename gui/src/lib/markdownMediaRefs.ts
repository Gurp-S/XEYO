import {mediaUrl} from '@/lib/api';

/**
 * 渲染前归一化：把 markdown 图片里的 `xeyo-media://<digest>` 引用改写为**当前后端
 * 只读地址**（#13 粘贴图片链的渲染端）。
 *
 * 为什么在文本层做：streamdown 的 markdown 渲染链默认 `urlTransform` 只放行
 * http(s)/data 等协议，自有协议会被清成空 src；且 static/流式两条路径的
 * 组件层拿到的已是清洗后的值——唯一可靠的位置是在解析之前改写原文。
 * 只动 `![alt](xeyo-media://<64hex>)` 这一形态，其余原样返回。
 */
export function resolveMediaRefsInMarkdown(md: string): string {
	if (!md || !md.includes('xeyo-media://')) {
		return md;
	}
	return md.replace(
		/(!\[[^\]]*\]\()xeyo-media:\/\/([0-9a-f]{64})(\))/gi,
		(match, head: string, digest: string, tail: string) => {
			const url = mediaUrl(`xeyo-media://${digest}`);
			return url ? `${head}${url}${tail}` : match;
		},
	);
}
