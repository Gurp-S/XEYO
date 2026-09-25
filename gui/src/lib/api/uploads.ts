/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec api7: uploads，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 *
 * 这两个函数是"抛错型"客户端：调用方靠 try/catch 决定附件能不能进消息。
 * 所以 200 也要校验回执——字段缺失或为空时若照样返回，调用方就把
 * "没确认收下"的附件当成已上传发出去了。
 */
import {apiUrl} from '@/lib/apiBase';
import {formatErrorDetail} from './core';
import {MediaUploadResult} from '../api';

/**
 * `/v1/files` 的回执。`truncated` 是服务端自己砍过正文的旗标
 * （超过 `_MAX_INLINE_CHARS` 时截断并追加 `…[truncated]`，源码注释写"不静默吞掉"）——
 * 客户端不读它就等于替它静默。
 */
export type FileUploadReceipt = {
	id: string;
	filename: string;
	bytes: number;
	text: string;
	path: string;
	truncated: boolean;
};

async function postFile(
	path: string,
	file: File,
	what: string,
): Promise<Record<string, unknown>> {
	const form = new FormData();
	form.append('file', file);
	let res: Response;
	try {
		res = await fetch(apiUrl(path), {method: 'POST', body: form});
	} catch (err) {
		throw new Error(
			`无法连接${what}（${err instanceof Error ? err.message : String(err)}）`,
		);
	}
	const payload = await res.json().catch(() => null);
	if (!res.ok) {
		throw new Error(formatErrorDetail(payload, res.status));
	}
	if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
		throw new Error(
			`${what}回执不是对象（HTTP ${res.status}）：未确认收下，请勿当作已上传`,
		);
	}
	return payload as Record<string, unknown>;
}

function needStr(body: Record<string, unknown>, key: string, what: string): string {
	const v = body[key];
	if (typeof v !== 'string' || !v.trim()) {
		throw new Error(`${what}回执缺 ${key}：未确认收下，请勿当作已上传`);
	}
	return v;
}

export async function uploadMedia(file: File): Promise<MediaUploadResult> {
	const body = await postFile('/v1/media/upload', file, '图片上传接口');
	if (body.ok !== true) {
		// 服务端错误走 HTTP 非 2xx；200 却不带 ok 就是回执形状变了，不能当成功。
		throw new Error('图片上传回执没有确认 ok：未确认收下，请勿当作已上传');
	}
	return {
		media_ref: needStr(body, 'media_ref', '图片上传'),
		mime: typeof body.mime === 'string' ? body.mime : '',
		width: Number(body.width) || 0,
		height: Number(body.height) || 0,
		bytes: Number(body.bytes) || 0,
		original_bytes: Number(body.original_bytes) || 0,
		filename: typeof body.filename === 'string' ? body.filename : file.name,
	};
}

export async function uploadFile(file: File): Promise<FileUploadReceipt> {
	const body = await postFile('/v1/files', file, '后端上传接口');
	if (typeof body.text !== 'string') {
		// 空文件是合法的空串，缺字段才是回执不完整。
		throw new Error('文件上传回执缺 text：未确认收下，请勿当作已上传');
	}
	return {
		id: needStr(body, 'id', '文件上传'),
		filename: needStr(body, 'filename', '文件上传'),
		bytes: Number(body.bytes) || 0,
		text: body.text,
		path: typeof body.path === 'string' ? body.path : '',
		truncated: body.truncated === true,
	};
}
