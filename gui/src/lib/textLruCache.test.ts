import {describe, expect, it} from 'vitest';
import {TextLruCache, TEXT_CACHE_MAX_CHARS} from './textLruCache';

describe('TextLruCache', () => {
	it('按最近使用淘汰，同时遵守条数和文本预算', () => {
		const cache = new TextLruCache<string>(2, 20, text => text.length);
		cache.set('a', '111'); cache.set('b', '222');
		expect(cache.get('a')).toBe('111');
		cache.set('c', '333');
		expect(cache.get('b')).toBeUndefined();
		expect(cache.size).toBe(2);
		cache.set('d', 'x'.repeat(16));
		expect(cache.get('a')).toBeUndefined();
		expect(cache.get('c')).toBeUndefined();
		expect(cache.retainedChars).toBe(17);
	});
	it('覆盖相同键不累加旧值，空字符串仍能命中', () => {
		const cache = new TextLruCache<string>(2, 20, text => text.length);
		cache.set('key', '12345'); cache.set('key', '');
		expect(cache.get('key')).toBe('');
		expect(cache.size).toBe(1);
		expect(cache.retainedChars).toBe(3);
	});
	it('单条超限不清空已有热缓存，替换超限项不留下旧值', () => {
		const cache = new TextLruCache<string>(2, 10, text => text.length);
		cache.set('a', '1'); cache.set('b', '2');
		cache.set('large', 'x'.repeat(20));
		expect(cache.size).toBe(2);
		cache.set('a', 'x'.repeat(20));
		expect(cache.get('a')).toBeUndefined();
		expect(cache.get('b')).toBe('2');
		expect(cache.retainedChars).toBe(2);
	});
	it('零条数预算不缓存', () => {
		const cache = new TextLruCache<string>(0, 10, text => text.length);
		cache.set('a', 'b');
		expect(cache.size).toBe(0);
		expect(cache.retainedChars).toBe(0);
	});
	it('同一 200 篇大文档的 A/B：保留量 4000 万降为 400 万字符，近期输出相同', () => {
		const oldCache = new Map<string, string>();
		const cache = new TextLruCache<string>(200, TEXT_CACHE_MAX_CHARS, text => text.length);
		for (let i = 0; i < 200; i++) {
			const text = `${i}`.padEnd(100_000, 'x');
			oldCache.set(text, text);
			cache.set(text, text);
			expect(cache.get(text)).toBe(oldCache.get(text));
			expect(cache.retainedChars).toBeLessThanOrEqual(TEXT_CACHE_MAX_CHARS);
		}
		const oldChars = [...oldCache].reduce((n, [key, value]) => n + key.length + value.length, 0);
		console.info('PERF cache retained character accounting:', {before: oldChars, after: cache.retainedChars});
		expect(oldChars).toBe(40_000_000);
		expect(cache.retainedChars).toBe(4_000_000);
	});
});
