export type CompressionState = 'idle' | 'compressing' | 'complete';
export type CompressionSource = 'automatic' | 'manual';
export type AgentState =
  | 'idle'
  | 'thinking'
  | 'tooling'
  | 'browser'
  | 'coding'
  | 'success'
  | 'error';

export type ContextSource = 'runtime' | 'stream' | 'snapshot' | 'fallback' | 'simulator';
export type ContextDataQuality = 'measured' | 'estimated' | 'fallback' | 'stale';

export type ContextSnapshot = {
  currentTokens: number;
  contextLimit: number | null;
  usagePercent: number | null;
  compressionState: CompressionState;
  compressionSource?: CompressionSource;
  agentState: AgentState;
  contextSource: ContextSource;
  dataQuality: ContextDataQuality;
  lastUpdatedAt?: number;
  isStale: boolean;
};

export type PastureStageId = 0 | 1 | 2 | 3 | 4 | 5;

export type PastureStage = {
  id: PastureStageId;
  name: string;
  label: string;
  from: number;
  to: number;
};

export const STALE_CONTEXT_AFTER_MS = 30_000;

export const PASTURE_STAGES: readonly PastureStage[] = [
  {id: 0, name: 'Seed', label: '种子', from: 0, to: 10},
  {id: 1, name: 'Meadow', label: '草甸', from: 10, to: 30},
  {id: 2, name: 'Animal Meadow', label: '动物草甸', from: 30, to: 50},
  {id: 3, name: 'Little Ecosystem', label: '小生态', from: 50, to: 70},
  {id: 4, name: 'Rich Pasture', label: '丰茂牧场', from: 70, to: 90},
  {id: 5, name: 'Full Pasture', label: '完整牧场', from: 90, to: 100},
];

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function hasFinite(value: unknown): boolean {
  return typeof value === 'number' && Number.isFinite(value);
}

export function clampPercent(value: number): number {
  return Math.min(100, Math.max(0, value));
}

export function normalizeContextSnapshot(
  input: Partial<ContextSnapshot> | null | undefined,
  fallbackAgentState: AgentState = 'idle',
): ContextSnapshot {
  // 未知窗口 → 一律 null（显示「暂无数据」），绝不伪造一个窗口来算百分比。
  const hasLimit = hasFinite(input?.contextLimit) && Number(input?.contextLimit) > 0;
  const limit = hasLimit ? Math.round(Number(input?.contextLimit)) : null;
  const hasPercent = hasFinite(input?.usagePercent);
  const suppliedPercent = finiteNumber(input?.usagePercent, Number.NaN);
  const hasTokens = hasFinite(input?.currentTokens);
  const suppliedTokens = Math.max(
    0,
    Math.round(finiteNumber(input?.currentTokens, 0)),
  );
  const percent = hasPercent
    ? clampPercent(suppliedPercent)
    : limit != null
      ? clampPercent((suppliedTokens / limit) * 100)
      : null;
  const tokens = limit != null
    ? Math.min(limit, Math.max(0, Math.round(((percent ?? 0) / 100) * limit)))
    : suppliedTokens;
  const compressionState = input?.compressionState ?? 'idle';
  const agentState = input?.agentState ?? fallbackAgentState;
  const source = input?.contextSource ?? (
    hasPercent || hasTokens
      ? hasLimit
        ? 'runtime'
        : 'stream'
      : 'fallback'
  );
  const quality = input?.dataQuality ?? (
    source === 'fallback'
      ? 'fallback'
      : hasPercent && hasLimit
        ? 'measured'
        : 'estimated'
  );
  const lastUpdatedAt = input?.lastUpdatedAt ?? (
    hasPercent || hasTokens ? Date.now() : undefined
  );
  const isStale = input?.isStale ?? (
    quality === 'stale' || (
      typeof lastUpdatedAt === 'number' && Date.now() - lastUpdatedAt > STALE_CONTEXT_AFTER_MS
    )
  );
  return {
    currentTokens: tokens,
    contextLimit: limit,
    usagePercent: percent,
    compressionState,
    compressionSource: input?.compressionSource,
    agentState,
    contextSource: source,
    dataQuality: isStale ? 'stale' : quality,
    lastUpdatedAt,
    isStale,
  };
}

export function stageForPercent(percent: number): PastureStage {
  const value = clampPercent(percent);
  return (
    PASTURE_STAGES.find(stage => value < stage.to || stage.id === 5) ??
    PASTURE_STAGES[5]
  );
}

export function animalBudget(percent: number): number {
  const value = clampPercent(percent);
  if (value < 20) return 0;
  if (value < 40) return 1;
  if (value < 60) return 2;
  if (value < 75) return 4;
  if (value < 90) return 6;
  return 8;
}

export function plantDensity(percent: number): number {
  return Math.min(1, Math.max(0, clampPercent(percent) / 100));
}

export function snapshotFromUsage(
  usage: {
    promptTokens?: number;
    completionTokens?: number;
    contextTokens?: number;
    contextLimit?: number;
    usedTokens?: number;
  } | null | undefined,
  agentState: AgentState = 'idle',
): ContextSnapshot {
  const hasContextTokens = hasFinite(usage?.contextTokens);
  const currentTokens = Math.max(
    0,
    Math.round(
      finiteNumber(
        usage?.contextTokens,
        finiteNumber(usage?.promptTokens, finiteNumber(usage?.usedTokens, 0)),
      ),
    ),
  );
  // 窗口未知 → null（显示「暂无数据」），绝不伪造窗口。
  const contextLimit = hasFinite(usage?.contextLimit) && Number(usage?.contextLimit) > 0
    ? Math.round(Number(usage?.contextLimit))
    : null;
  return normalizeContextSnapshot(
    {
      currentTokens,
      contextLimit,
      agentState,
      contextSource: hasContextTokens && contextLimit != null ? 'runtime' : 'stream',
      dataQuality: hasContextTokens && contextLimit != null ? 'measured' : 'estimated',
      lastUpdatedAt: Date.now(),
      isStale: false,
    },
    agentState,
  );
}
