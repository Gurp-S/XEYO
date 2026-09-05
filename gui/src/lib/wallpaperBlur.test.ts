import {describe, expect, it} from 'vitest';
import {effectiveWallpaperBlurCap} from './wallpaperBlur';

describe('effectiveWallpaperBlurCap', () => {
	it('caps blur under reduced motion', () => {
		const original = window.matchMedia;
		window.matchMedia = ((query: string) =>
			({
				matches: String(query).includes('prefers-reduced-motion'),
				media: query,
				addEventListener: () => undefined,
				removeEventListener: () => undefined,
			}) as unknown as MediaQueryList) as typeof window.matchMedia;
		expect(effectiveWallpaperBlurCap(40)).toBe(8);
		expect(effectiveWallpaperBlurCap(4)).toBe(4);
		window.matchMedia = original;
	});
});
