import {TextLruCache, TEXT_CACHE_MAX_CHARS} from './textLruCache';

/** Text preparation stays independent from the deferred Markdown renderer. */
export function sanitizeMarkdown(content: string): string {
	return content ? content.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '') : '';
}

export function promoteDisplayMath(content: string): string {
	if (!content.includes('$$')) return content;
	return content.replace(/^[ \t]*\$\$([^$\n][^]*?)\$\$[ \t]*$/gm,
		(_m, inner: string) => `$$\n${String(inner).trim()}\n$$`);
}

const cache = new TextLruCache<string>(200, TEXT_CACHE_MAX_CHARS, text => text.length);
export function prepareStaticMarkdown(markdown: string): string {
	const hit = cache.get(markdown);
	if (hit !== undefined) return hit;
	const safe = promoteDisplayMath(sanitizeMarkdown(markdown));
	cache.set(markdown, safe);
	return safe;
}
