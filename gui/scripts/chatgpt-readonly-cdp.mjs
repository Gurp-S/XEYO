#!/usr/bin/env node

/**
 * Read-only inspector for the currently focused ChatGPT tab.
 *
 * Safety boundary:
 * - attaches to an already-running Chromium/Edge CDP endpoint;
 * - never creates a page, navigates, clicks, types, submits, or sends;
 * - only evaluates a fixed DOM snapshot function on the selected tab;
 * - refuses to guess when there is not exactly one focused ChatGPT tab.
 *
 * Usage from gui/:
 *   node scripts/chatgpt-readonly-cdp.mjs --endpoint http://127.0.0.1:9222
 *   node scripts/chatgpt-readonly-cdp.mjs --endpoint http://127.0.0.1:9222 --out ../_wsc_out/chatgpt-readonly.json
 *   node scripts/chatgpt-readonly-cdp.mjs --endpoint http://127.0.0.1:9222 --list
 *   node scripts/chatgpt-readonly-cdp.mjs --self-test
 */

import {writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {chromium} from 'playwright';

const ALLOWED_HOSTS = new Set(['chatgpt.com', 'www.chatgpt.com', 'chat.openai.com']);
const DEFAULT_TEXT_LIMIT = 40_000;
const DEFAULT_MESSAGE_LIMIT = 120;
const DEFAULT_MESSAGE_TEXT_LIMIT = 12_000;

function usage() {
	console.log(`Usage:
  node scripts/chatgpt-readonly-cdp.mjs --endpoint <http://127.0.0.1:9222> [options]

Options:
  --endpoint <url>       Existing CDP HTTP endpoint. Required unless CHATGPT_CDP_ENDPOINT is set.
  --target-id <id>       Inspect exactly this CDP target after URL validation.
  --list                 List eligible ChatGPT targets without reading page text.
  --out <path>           Write the read-only snapshot JSON to this local path.
  --text-limit <n>       Maximum body/article text characters (default: ${DEFAULT_TEXT_LIMIT}).
  --self-test            Run local selector/extraction safety tests; no browser connection.
  --help                 Show this help.

The adapter does not support navigation, clicking, keyboard input, form access, or message sending.`);
}

function parseArgs(argv) {
	const args = {endpoint: process.env.CHATGPT_CDP_ENDPOINT ?? '', targetId: '', out: '', list: false,
		textLimit: DEFAULT_TEXT_LIMIT, selfTest: false, help: false};
	for (let i = 0; i < argv.length; i += 1) {
		const arg = argv[i];
		if (arg === '--help' || arg === '-h') args.help = true;
		else if (arg === '--list') args.list = true;
		else if (arg === '--self-test') args.selfTest = true;
		else if (arg === '--endpoint') args.endpoint = argv[++i] ?? '';
		else if (arg === '--target-id') args.targetId = argv[++i] ?? '';
		else if (arg === '--out') args.out = argv[++i] ?? '';
		else if (arg === '--text-limit') args.textLimit = Number(argv[++i]);
		else throw new Error(`未知参数: ${arg}`);
	}
	if (!Number.isInteger(args.textLimit) || args.textLimit < 1 || args.textLimit > 1_000_000) {
		throw new Error('--text-limit 必须是 1 到 1000000 的整数');
	}
	return args;
}

function assertLocalEndpoint(raw) {
	let url;
	try {
		url = new URL(raw);
	} catch {
		throw new Error(`CDP endpoint 不是有效 URL: ${raw}`);
	}
	if (!['http:', 'https:'].includes(url.protocol)) {
		throw new Error('CDP endpoint 必须是 http:// 或 https:// 地址');
	}
	if (!['127.0.0.1', 'localhost', '::1'].includes(url.hostname)) {
		throw new Error('为避免把浏览器控制权暴露到网络，CDP endpoint 只允许本机地址');
	}
}

function jsonListUrl(endpoint) {
	const url = new URL(endpoint);
	if (url.pathname.endsWith('/json/version') || url.pathname.endsWith('/json/list')) {
		url.pathname = url.pathname.replace(/\/json\/(version|list)$/, '');
	}
	url.search = '';
	url.hash = '';
	return `${url.toString().replace(/\/$/, '')}/json/list`;
}

async function readCdpTargets(endpoint) {
	const response = await fetch(jsonListUrl(endpoint));
	if (!response.ok) throw new Error(`读取 CDP target 列表失败: HTTP ${response.status}`);
	const value = await response.json();
	return Array.isArray(value) ? value.filter(item => item?.type === 'page') : [];
}

export function isAllowedChatGPTUrl(rawUrl) {
	try {
		const url = new URL(rawUrl);
		return url.protocol === 'https:' && ALLOWED_HOSTS.has(url.hostname);
	} catch {
		return false;
	}
}

function pageIdentity(page) {
	return page.evaluate(() => ({
		url: window.location.href,
		title: document.title,
		visibilityState: document.visibilityState,
		hasFocus: document.hasFocus(),
		readyState: document.readyState,
	}));
}

/** @param {Array<{page: any, identity: any, targetId?: string}>} candidates */
export function selectCurrentCandidate(candidates, targetId = '') {
	const allowed = candidates.filter(item => isAllowedChatGPTUrl(item.identity.url));
	if (targetId) {
		const exact = allowed.filter(item => item.targetId === targetId);
		if (exact.length !== 1) throw new Error(`指定的 ChatGPT target 不存在或不是允许的页面: ${targetId}`);
		return exact[0];
	}
	const focused = allowed.filter(item => item.identity.visibilityState === 'visible' && item.identity.hasFocus);
	if (focused.length !== 1) {
		const summary = allowed.map(item => ({
			targetId: item.targetId ?? null,
			url: item.identity.url,
			visibilityState: item.identity.visibilityState,
			hasFocus: item.identity.hasFocus,
		}));
		throw new Error(`无法唯一确定当前 ChatGPT 标签页（候选数=${focused.length}）。请使用 --target-id。候选: ${JSON.stringify(summary)}`);
	}
	return focused[0];
}

function clampText(value, limit) {
	const text = String(value ?? '');
	return text.length <= limit ? text : `${text.slice(0, limit)}\n[truncated: ${text.length - limit} chars]`;
}

// Fixed, read-only DOM function. Do not replace with caller-supplied JavaScript.
function readOnlySnapshot({textLimit, messageLimit, messageTextLimit}) {
	const root = document.querySelector('main') ?? document.body;
	const text = root?.innerText ?? '';
	const nodes = [...document.querySelectorAll('[data-message-author-role], article')];
	const messages = [];
	const seen = new Set();
	for (const node of nodes) {
		const content = (node.innerText ?? '').trim();
		if (!content) continue;
		const key = `${node.getAttribute('data-message-author-role') ?? ''}\n${content}`;
		if (seen.has(key)) continue;
		seen.add(key);
		messages.push({
			role: node.getAttribute('data-message-author-role') ?? null,
			text: content,
		});
		if (messages.length >= messageLimit) break;
	}
	return {
		url: window.location.href,
		title: document.title,
		capturedAtInPage: new Date().toISOString(),
		visibilityState: document.visibilityState,
		hasFocus: document.hasFocus(),
		readyState: document.readyState,
		bodyText: text.length <= textLimit ? text : `${text.slice(0, textLimit)}\n[truncated]`,
		messages: messages.map(item => ({
			role: item.role,
			text: item.text.length <= messageTextLimit ? item.text : `${item.text.slice(0, messageTextLimit)}\n[truncated]`,
		})),
		counts: {
			article: document.querySelectorAll('article').length,
			roleMessages: document.querySelectorAll('[data-message-author-role]').length,
			links: document.querySelectorAll('a').length,
		},
	};
}

function assert(condition, message) {
	if (!condition) throw new Error(`self-test failed: ${message}`);
}

export function runSelfTest() {
	assert(isAllowedChatGPTUrl('https://chatgpt.com/c/abc'), 'chatgpt.com should be allowed');
	assert(isAllowedChatGPTUrl('https://chat.openai.com/'), 'chat.openai.com should be allowed');
	assert(!isAllowedChatGPTUrl('http://chatgpt.com/c/abc'), 'http must be rejected');
	assert(!isAllowedChatGPTUrl('https://evil.example/chatgpt.com'), 'other hosts must be rejected');
	const fakePage = {};
	const selected = selectCurrentCandidate([
		{page: fakePage, targetId: 'a', identity: {url: 'https://chatgpt.com/c/a', visibilityState: 'hidden', hasFocus: false}},
		{page: fakePage, targetId: 'b', identity: {url: 'https://chatgpt.com/c/b', visibilityState: 'visible', hasFocus: true}},
		{page: fakePage, targetId: 'c', identity: {url: 'https://example.com', visibilityState: 'visible', hasFocus: true}},
	], '');
	assert(selected.targetId === 'b', 'must select the focused allowed tab only');
	assert(selectCurrentCandidate([
		{page: fakePage, targetId: 'a', identity: {url: 'https://chatgpt.com/c/a', visibilityState: 'hidden', hasFocus: false}},
	], 'a').targetId === 'a', 'explicit target id should work after URL validation');
	console.log('chatgpt-readonly-cdp self-test: ok');
}

async function inspect(args) {
	if (!args.endpoint) throw new Error('缺少 --endpoint，或设置 CHATGPT_CDP_ENDPOINT');
	assertLocalEndpoint(args.endpoint);
	const cdpTargets = (await readCdpTargets(args.endpoint)).filter(target => isAllowedChatGPTUrl(target.url));
	const browser = await chromium.connectOverCDP(args.endpoint);
	try {
		const pages = browser.contexts().flatMap(context => context.pages());
		const candidates = [];
		for (const page of pages) {
			// URL is the only property read from non-ChatGPT pages. No DOM, title,
			// focus state, form state, or page text is inspected outside the allowlist.
			if (!isAllowedChatGPTUrl(page.url())) continue;
			const identity = await pageIdentity(page);
			const matchingTargets = cdpTargets.filter(target =>
				target.url === identity.url && (target.title ?? '') === (identity.title ?? ''));
			// A target id is taken only from the browser's read-only /json/list response;
			// never from Playwright private fields, which are not a stable contract.
			const targetId = matchingTargets.length === 1 ? matchingTargets[0].id : '';
			candidates.push({page, identity, targetId});
		}
		const allowed = candidates.filter(item => isAllowedChatGPTUrl(item.identity.url));
		if (args.list) {
			console.log(JSON.stringify({
				readOnly: true,
				endpoint: args.endpoint,
				candidates: allowed.map(item => ({targetId: item.targetId || null, ...item.identity})),
			}, null, 2));
			return;
		}
		const selected = selectCurrentCandidate(candidates, args.targetId);
		const snapshot = await selected.page.evaluate(readOnlySnapshot, {
			textLimit: args.textLimit,
			messageLimit: DEFAULT_MESSAGE_LIMIT,
			messageTextLimit: DEFAULT_MESSAGE_TEXT_LIMIT,
		});
		const result = {
			readOnly: true,
			adapter: 'chatgpt-readonly-cdp-v1',
			endpoint: args.endpoint,
			targetId: selected.targetId || null,
			capturedAt: new Date().toISOString(),
			selection: 'focused-visible-allowed-chatgpt-tab',
			operations: ['connectOverCDP', 'page.evaluate(readOnlySnapshot)'],
			snapshot,
		};
		const encoded = `${JSON.stringify(result, null, 2)}\n`;
		if (args.out) {
			const output = resolve(args.out);
			await writeFile(output, encoded, 'utf8');
			console.log(JSON.stringify({ok: true, output, ...result.snapshot, messageCount: result.snapshot.messages.length}, null, 2));
		} else {
			console.log(encoded);
		}
	} finally {
		// This is an attach-only adapter. Never call browser.close(), because the
		// connected browser belongs to the user. disconnect() drops our CDP session
		// while leaving Edge/Chromium and all tabs running.
		// Playwright's CDP Browser implementation may not expose disconnect().
		// Never substitute browser.close(): that would close the user's Edge.
		if (typeof browser.disconnect === 'function') browser.disconnect();
	}
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	if (args.help) return usage();
	if (args.selfTest) return runSelfTest();
	await inspect(args);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	main().catch(error => {
		console.error(`chatgpt-readonly-cdp: ${error.message}`);
		process.exitCode = 1;
	});
}
