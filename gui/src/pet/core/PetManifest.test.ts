import {describe, expect, it} from 'vitest';
import {
  getPetBubbleUrl,
  normalizePetCatalog,
  normalizePetManifest,
  resolvePetState,
} from './PetManifest';

const manifest = {
  id: 'test-pet',
  displayName: 'Test Pet',
  spritesheetPath: 'atlas.webp',
  cellSize: {width: 192, height: 208},
  columns: 8,
  rows: 2,
  stateRows: [
    {state: 'idle', row: 0, frames: 2},
    {state: 'happy', row: 1, frames: 1, bubbleOverlay: 'bubbles/sample.png'},
  ],
  bubbleOverlays: [
    {id: 'sample-bubble', path: 'bubbles/sample.png', kind: 'speech'},
  ],
};

describe('XeyoPet manifest protocol', () => {
  it('normalizes atlas geometry and resolves relative assets from manifest URL', () => {
    const loaded = normalizePetManifest(manifest, '/XeyoPet/test-pet.json');
		expect(loaded.sheetUrl).toMatch(/\/XeyoPet\/atlas\.webp$/);
    expect(loaded.stateRows.get('idle')?.frames).toBe(2);
    expect(getPetBubbleUrl(loaded, 'idle')).toBeUndefined();
    expect(getPetBubbleUrl(loaded, 'happy')).toMatch(
      /\/XeyoPet\/bubbles\/sample\.png$/,
    );
  });

		it('suppresses an external bubble when the atlas already contains it', () => {
			const loaded = normalizePetManifest(
				{
					...manifest,
					stateRows: [
						...manifest.stateRows,
						{
							state: 'thinking',
							row: 0,
							frames: 1,
                bubbleOverlay: 'bubbles/sample.png',
							bubbleInAtlas: true,
						},
					],
				},
				'/XeyoPet/test-pet.json',
			);
			expect(getPetBubbleUrl(loaded, 'thinking')).toBeUndefined();
		});

  it('normalizes a bubble-only animation region without changing the character layer', () => {
    const loaded = normalizePetManifest(
      {
        ...manifest,
        stateRows: [
          ...manifest.stateRows,
          {
            state: 'sleeping',
            row: 0,
            frames: 2,
            animationMode: 'bubble-only',
            animationRegion: {x: 116, y: 24, width: 68, height: 64},
          },
        ],
      },
      '/XeyoPet/test-pet.json',
    );
    expect(loaded.stateRows.get('sleeping')?.animationMode).toBe('bubble-only');
    expect(loaded.stateRows.get('sleeping')?.animationRegion).toEqual({
      x: 116,
      y: 24,
      width: 68,
      height: 64,
    });
  });

  it('rejects bubble-only animation without a bounded region', () => {
    expect(() =>
      normalizePetManifest(
        {
          ...manifest,
          stateRows: [
            ...manifest.stateRows,
            {state: 'sleeping', row: 0, frames: 1, animationMode: 'bubble-only'},
          ],
        },
        '/XeyoPet/test-pet.json',
      ),
    ).toThrow(/animationRegion/);
  });

  it('falls back unknown states to idle', () => {
    const loaded = normalizePetManifest(manifest, '/XeyoPet/test-pet.json');
    expect(resolvePetState(loaded, 'missing-state')).toBe('idle');
  });

  it('rejects a manifest without an idle row or with frames beyond columns', () => {
    expect(() =>
      normalizePetManifest(
        {...manifest, stateRows: [{state: 'happy', row: 0, frames: 1}]},
        '/XeyoPet/test-pet.json',
      ),
    ).toThrow(/idle/);
    expect(() =>
      normalizePetManifest(
        {
          ...manifest,
          stateRows: [{state: 'idle', row: 0, frames: 9}],
        },
        '/XeyoPet/test-pet.json',
      ),
    ).toThrow(/columns/);
  });

  it('normalizes a fixed catalog and chooses an enabled default', () => {
    const catalog = normalizePetCatalog({
      version: 1,
      defaultPetId: 'not-enabled',
      pets: [
        {id: 'disabled', manifestPath: 'disabled.json', enabled: false},
        {id: 'test-pet', manifestPath: 'pet.json', enabled: true},
      ],
    });
    expect(catalog.defaultPetId).toBe('test-pet');
  });
});
