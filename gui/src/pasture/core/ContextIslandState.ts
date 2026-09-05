import type {AgentState, ContextSnapshot} from '@/pasture/context/ContextStage';

export type IslandCompanionVisibility = 'hidden' | 'head' | 'full';
export type IslandCompanionMode =
  | 'idle'
  | 'thinking'
  | 'happy'
  | 'react'
  | 'compression'
  | 'sleep'
  | 'alert'
  | 'empty';

export type CharacterLocation = 'island' | 'dragging' | 'desktop';

export type IslandLoadState = {
  coconutCount: number;
  starCount: number;
  companionVisibility: IslandCompanionVisibility;
};
export type IslandEventState = {
  compressionActive: boolean;
  alertActive: boolean;
  eventMode: IslandCompanionMode | null;
};

export type DerivedIslandState = IslandLoadState & {
  characterLocation: CharacterLocation;
  companionMode: IslandCompanionMode;
  fallenCoconutCount: number;
  isCompressing: boolean;
};

export const MAX_STARS = 12;
export const COCONUT_THRESHOLDS = [25, 50, 75, 90] as const;
export const CHARACTER_VISIBLE_AT = 50;
export const CHARACTER_FULL_AT = 60;
export const CHARACTER_REACT_AT = 75;

export function clampIslandPercent(value: number): number {
  return Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0));
}

/** 把可空的使用率映射为 0–100；未知（null）视为空岛（0）。 */
export function percentOf(snapshot: Pick<ContextSnapshot, 'usagePercent'>): number {
  const v = snapshot.usagePercent;
  return typeof v === 'number' && Number.isFinite(v) ? clampIslandPercent(v) : 0;
}

export function coconutCountForPercent(percent: number): number {
  const value = clampIslandPercent(percent);
  return COCONUT_THRESHOLDS.filter(threshold => value >= threshold).length;
}

export function starCountForPercent(percent: number): number {
  const value = clampIslandPercent(percent);
  if (value < 25) return 0;
  if (value < 50) return 4;
  if (value < 75) return 8;
  return MAX_STARS;
}

export function companionVisibilityForPercent(percent: number): IslandCompanionVisibility {
  const value = clampIslandPercent(percent);
  if (value < CHARACTER_VISIBLE_AT) return 'hidden';
  if (value < CHARACTER_FULL_AT) return 'head';
  return 'full';
}

export function fallenCoconutCountForPercent(percent: number): number {
  const value = clampIslandPercent(percent);
  if (value < 25) return 0;
  const onTree = coconutCountForPercent(value);
  // During compression the tree keeps at most 2; the rest fall to the ground.
  return Math.max(0, onTree - Math.min(2, onTree));
}

/** Whether a context load change crosses the 75% reaction node (one-shot). */
export function shouldTriggerReaction(prev: number, current: number): boolean {
  return prev < CHARACTER_REACT_AT && current >= CHARACTER_REACT_AT;
}

export function loadStateForSnapshot(
  snapshot: Pick<ContextSnapshot, 'usagePercent'>,
): IslandLoadState {
  const percent = percentOf(snapshot);
  return {
    coconutCount: coconutCountForPercent(percent),
    starCount: starCountForPercent(percent),
    companionVisibility: companionVisibilityForPercent(percent),
  };
}

export function eventModeForAgentState(state: AgentState): IslandCompanionMode | null {
  switch (state) {
    case 'thinking':
    case 'tooling':
    case 'browser':
    case 'coding':
      return 'thinking';
    case 'success':
      return 'happy';
    case 'error':
      return 'alert';
    case 'idle':
    default:
      return null;
  }
}

export function resolveCompanionMode(
  snapshot: Pick<ContextSnapshot, 'usagePercent'>,
  events: IslandEventState,
): IslandCompanionMode {
  const visibility = companionVisibilityForPercent(percentOf(snapshot));
  if (visibility === 'hidden') return 'idle';
  if (events.compressionActive) return 'compression';
  if (events.alertActive) return 'alert';
  return events.eventMode ?? 'idle';
}

export function deriveIslandState(
  snapshot: Pick<ContextSnapshot, 'usagePercent'>,
  events: IslandEventState = {compressionActive: false, alertActive: false, eventMode: null},
): DerivedIslandState {
  const load = loadStateForSnapshot(snapshot);
  return {
    ...load,
    characterLocation: 'island',
    companionMode: resolveCompanionMode(snapshot, events),
    fallenCoconutCount: events.compressionActive
      ? fallenCoconutCountForPercent(percentOf(snapshot))
      : 0,
    isCompressing: events.compressionActive,
  };
}

export function tooltipForIsland(
  snapshot: Pick<ContextSnapshot, 'usagePercent'>,
  compressionActive: boolean,
  eventMode: IslandCompanionMode | null,
): string {
  if (compressionActive) return '正在压缩上下文记忆';
  if (eventMode === 'thinking') return 'Agent 正在思考';
  if (eventMode === 'happy') return '任务已完成';
  if (eventMode === 'react') return '上下文突破 75%，小岛角色很开心';
  if (eventMode === 'alert') return '上下文即将到达上限';
  if (eventMode === 'sleep') return '上下文已压缩，角色正在休息';
  if (snapshot.usagePercent == null) return '上下文负载：暂无数据';
  return `上下文记忆负载：${Math.round(clampIslandPercent(snapshot.usagePercent))}%`;
}
