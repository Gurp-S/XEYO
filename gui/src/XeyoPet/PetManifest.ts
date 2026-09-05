import type {
  LoadedPetManifest,
  PetAnimationMode,
  PetAnimationRegion,
  PetBubbleOverlay,
  PetCatalog,
  PetCatalogEntry,
  PetManifest,
  PetStateRow,
} from './types';

const FALLBACK_STATE = 'idle';

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function positiveInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || (value as number) <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
  return value as number;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`${label} must be a non-negative integer`);
  }
  return value as number;
}

function resolveAgainstManifest(assetPath: string, manifestUrl: string): string {
  const origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin;
  const manifestHref = new URL(manifestUrl, origin).href;
  return new URL(assetPath, manifestHref).href;
}

function normalizeCellSize(value: unknown): {width: number; height: number} {
  const input = record(value, 'cellSize');
  return {
    width: positiveInteger(input.width, 'cellSize.width'),
    height: positiveInteger(input.height, 'cellSize.height'),
  };
}

function normalizeAnimationRegion(
  value: unknown,
  index: number,
  cellSize: {width: number; height: number},
): PetAnimationRegion {
  const input = record(value, `stateRows[${index}].animationRegion`);
  const region: PetAnimationRegion = {
    x: nonNegativeInteger(input.x, `stateRows[${index}].animationRegion.x`),
    y: nonNegativeInteger(input.y, `stateRows[${index}].animationRegion.y`),
    width: positiveInteger(input.width, `stateRows[${index}].animationRegion.width`),
    height: positiveInteger(input.height, `stateRows[${index}].animationRegion.height`),
  };
  if (region.x + region.width > cellSize.width || region.y + region.height > cellSize.height) {
    throw new Error(`stateRows[${index}].animationRegion must fit inside cellSize`);
  }
  return region;
}

function normalizeStateRow(
  value: unknown,
  index: number,
  columns: number,
  rows: number,
  cellSize: {width: number; height: number},
): PetStateRow {
  const input = record(value, `stateRows[${index}]`);
  const state = requiredString(input.state, `stateRows[${index}].state`);
  const row = nonNegativeInteger(input.row, `stateRows[${index}].row`);
  const frames = positiveInteger(input.frames, `stateRows[${index}].frames`);
  if (row >= rows) {
    throw new Error(`stateRows[${index}].row must be less than rows`);
  }
  if (frames > columns) {
    throw new Error(`stateRows[${index}].frames must be less than or equal to columns`);
  }

  const normalized: PetStateRow = {state, row, frames};
  if (input.frameSequence !== undefined) {
    if (
      !Array.isArray(input.frameSequence) ||
      input.frameSequence.length === 0 ||
      input.frameSequence.some(
        item => !Number.isInteger(item) || (item as number) < 0 || (item as number) >= columns,
      )
    ) {
      throw new Error(`stateRows[${index}].frameSequence must contain valid atlas frame indexes`);
    }
    normalized.frameSequence = input.frameSequence as number[];
  }
  if (input.frameOffsetsX !== undefined) {
    if (
      !Array.isArray(input.frameOffsetsX) ||
      input.frameOffsetsX.some(item => !Number.isInteger(item))
    ) {
      throw new Error(`stateRows[${index}].frameOffsetsX must be an array of integers`);
    }
    normalized.frameOffsetsX = input.frameOffsetsX as number[];
  }
  if (input.fps !== undefined) {
    normalized.fps = positiveInteger(input.fps, `stateRows[${index}].fps`);
  }
  if (input.loop !== undefined) {
    if (typeof input.loop !== 'boolean') {
      throw new Error(`stateRows[${index}].loop must be a boolean`);
    }
    normalized.loop = input.loop;
  }
  if (input.animationMode !== undefined) {
    if (input.animationMode !== 'full' && input.animationMode !== 'bubble-only') {
      throw new Error(`stateRows[${index}].animationMode must be full or bubble-only`);
    }
    normalized.animationMode = input.animationMode as PetAnimationMode;
  }
  if (input.animationRegion !== undefined) {
    normalized.animationRegion = normalizeAnimationRegion(input.animationRegion, index, cellSize);
  }
  if (normalized.animationMode === 'bubble-only' && !normalized.animationRegion) {
    throw new Error(`stateRows[${index}].bubble-only animation requires animationRegion`);
  }
  if (normalized.animationMode !== 'bubble-only' && normalized.animationRegion) {
    throw new Error(`stateRows[${index}].animationRegion requires bubble-only animation`);
  }
  if (input.bubbleOverlay !== undefined) {
    normalized.bubbleOverlay = requiredString(
      input.bubbleOverlay,
      `stateRows[${index}].bubbleOverlay`,
    );
  }
  if (input.bubbleInAtlas !== undefined) {
    if (typeof input.bubbleInAtlas !== 'boolean') {
      throw new Error(`stateRows[${index}].bubbleInAtlas must be a boolean`);
    }
    normalized.bubbleInAtlas = input.bubbleInAtlas;
  }
  return normalized;
}

function normalizeBubbleOverlay(value: unknown, index: number): PetBubbleOverlay {
  const input = record(value, `bubbleOverlays[${index}]`);
  const normalized: PetBubbleOverlay = {
    id: requiredString(input.id, `bubbleOverlays[${index}].id`),
    path: requiredString(input.path, `bubbleOverlays[${index}].path`),
  };
  if (input.kind !== undefined) {
    normalized.kind = requiredString(input.kind, `bubbleOverlays[${index}].kind`);
  }
  if (input.useFor !== undefined) {
    if (!Array.isArray(input.useFor) || input.useFor.some(item => typeof item !== 'string')) {
      throw new Error(`bubbleOverlays[${index}].useFor must be an array of strings`);
    }
    normalized.useFor = input.useFor as string[];
  }
  return normalized;
}

export function normalizePetManifest(input: unknown, manifestUrl: string): LoadedPetManifest {
  const raw = record(input, 'pet manifest');
  const id = requiredString(raw.id, 'id');
  const displayName = requiredString(raw.displayName, 'displayName');
  const spritesheetPath = requiredString(raw.spritesheetPath, 'spritesheetPath');
  const cellSize = normalizeCellSize(raw.cellSize);
  const columns = positiveInteger(raw.columns, 'columns');
  const rows = positiveInteger(raw.rows, 'rows');

  if (!Array.isArray(raw.stateRows) || raw.stateRows.length === 0) {
    throw new Error('stateRows must be a non-empty array');
  }
  const stateRows = raw.stateRows.map((item, index) =>
    normalizeStateRow(item, index, columns, rows, cellSize),
  );
  const states = new Set<string>();
  for (const stateRow of stateRows) {
    if (states.has(stateRow.state)) {
      throw new Error(`duplicate state row: ${stateRow.state}`);
    }
    states.add(stateRow.state);
  }
  if (!states.has(FALLBACK_STATE)) {
    throw new Error('stateRows must include an idle fallback row');
  }

  const bubbleOverlays = Array.isArray(raw.bubbleOverlays)
    ? raw.bubbleOverlays.map((item, index) => normalizeBubbleOverlay(item, index))
    : [];
  const bubbleUrls = new Map<string, string>();
  for (const bubble of bubbleOverlays) {
    if (bubbleUrls.has(bubble.id) || bubbleUrls.has(bubble.path)) {
      throw new Error(`duplicate bubble overlay: ${bubble.id}`);
    }
    const url = resolveAgainstManifest(bubble.path, manifestUrl);
    bubbleUrls.set(bubble.id, url);
    bubbleUrls.set(bubble.path, url);
  }

  const manifest: PetManifest = {
    id,
    displayName,
    description: typeof raw.description === 'string' ? raw.description : undefined,
    spritesheetPath,
    cellSize,
    columns,
    rows,
    stateRows,
    bubbleOverlays,
    compatibility:
      raw.compatibility && typeof raw.compatibility === 'object'
        ? (raw.compatibility as PetManifest['compatibility'])
        : undefined,
  };

  return {
    manifest,
    baseUrl: new URL(manifestUrl, typeof window === 'undefined' ? 'http://localhost' : window.location.origin).href.replace(/[^/]+$/, ''),
    sheetUrl: resolveAgainstManifest(spritesheetPath, manifestUrl),
    stateRows: new Map(stateRows.map(stateRow => [stateRow.state, stateRow])),
    bubbleUrls,
  };
}

export function normalizePetCatalog(input: unknown): PetCatalog {
  const raw = record(input, 'pet catalog');
  if (raw.version !== 1) {
    throw new Error('pet catalog version must be 1');
  }
  if (!Array.isArray(raw.pets) || raw.pets.length === 0) {
    throw new Error('pet catalog pets must be a non-empty array');
  }
  const pets: PetCatalogEntry[] = raw.pets.map((item, index) => {
    const entry = record(item, `pets[${index}]`);
    return {
      id: requiredString(entry.id, `pets[${index}].id`),
      manifestPath: requiredString(entry.manifestPath, `pets[${index}].manifestPath`),
      enabled: entry.enabled === undefined ? true : Boolean(entry.enabled),
    };
  });
  const ids = new Set<string>();
  for (const pet of pets) {
    if (ids.has(pet.id)) {
      throw new Error(`duplicate pet id: ${pet.id}`);
    }
    ids.add(pet.id);
  }
  return {
    version: 1,
    defaultPetId:
      typeof raw.defaultPetId === 'string' && ids.has(raw.defaultPetId)
        ? raw.defaultPetId
        : pets.find(pet => pet.enabled !== false)?.id ?? pets[0].id,
    pets,
  };
}

export function getPetStateRow(
  loaded: LoadedPetManifest,
  state: string | undefined,
): PetStateRow {
  return loaded.stateRows.get(state ?? '') ?? loaded.stateRows.get(FALLBACK_STATE)!;
}

export function getPetBubbleUrl(
  loaded: LoadedPetManifest,
  state: string | undefined,
): string | undefined {
  const row = getPetStateRow(loaded, state);
  if (row.bubbleInAtlas) return undefined;
  return row.bubbleOverlay ? loaded.bubbleUrls.get(row.bubbleOverlay) : undefined;
}

export function resolvePetState(loaded: LoadedPetManifest, state: string | undefined): string {
  return loaded.stateRows.has(state ?? '') ? (state as string) : FALLBACK_STATE;
}
