/** XeyoPet：精灵表动画桌宠的类型与默认资源常量。 */

export type PetCellSize = {
	width: number;
	height: number;
};

export type PetAnimationMode = 'full' | 'bubble-only';

export type PetAnimationRegion = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PetStateRow = {
  state: string;
  row: number;
  frames: number;
  /** Optional atlas frame order; absent means 0..frames-1. */
  frameSequence?: number[];
  /** Optional per-atlas-frame horizontal correction in native pixels. */
  frameOffsetsX?: number[];
  fps?: number;
  loop?: boolean;
  /** Apply atlas frame changes only to a bounded region instead of the whole sprite. */
  animationMode?: PetAnimationMode;
  /** Native cell region used by localized animation modes. */
  animationRegion?: PetAnimationRegion;

  bubbleOverlay?: string;
  /** True when the state row already contains its bubble artwork inside the atlas. */
  bubbleInAtlas?: boolean;
};

export type PetBubbleOverlay = {
	id: string;
	path: string;
	kind?: string;
	useFor?: string[];
};

export type PetManifest = {
	id: string;
	displayName: string;
	description?: string;
	spritesheetPath: string;
	cellSize: PetCellSize;
	columns: number;
	rows: number;
	stateRows: PetStateRow[];
	bubbleOverlays: PetBubbleOverlay[];
	compatibility?: Record<string, unknown>;
};

export type LoadedPetManifest = {
	manifest: PetManifest;
	baseUrl: string;
	sheetUrl: string;
	stateRows: Map<string, PetStateRow>;
	bubbleUrls: Map<string, string>;
};

export type PetCatalogEntry = {
	id: string;
	manifestPath: string;
	enabled: boolean;
};

export type PetCatalog = {
	version: 1;
	defaultPetId?: string;
	pets: PetCatalogEntry[];
};

export const DEFAULT_XEYO_PET_BASE = '/XeyoPet';
export const DEFAULT_XEYO_PET_MANIFEST = 'pet-plus.json';

