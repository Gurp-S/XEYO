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
  /** 可选的图集帧顺序；缺省表示 0..frames-1。 */
  frameSequence?: number[];
  /** 可选的逐帧水平校正（原生像素）。 */
  frameOffsetsX?: number[];
  fps?: number;
  loop?: boolean;
  /** 仅对限定区域应用图集帧变更，而不是整个精灵。 */
  animationMode?: PetAnimationMode;
  /** 局部动画模式使用的原生单元格区域。 */
  animationRegion?: PetAnimationRegion;

  bubbleOverlay?: string;
  /** 为 true 表示该状态行已在图集内自带气泡图。 */
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

