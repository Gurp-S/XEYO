import {animalBudget, plantDensity, stageForPercent} from '@/pasture/context/ContextStage';

export type PastureSimulationScenario = {
  id: string;
  sessionId: string;
  seed: string;
  contextSequence: Array<{atMs: number; ratio: number | null}>;
  events: Array<{
    atMs: number;
    type:
      | 'compression-start'
      | 'compression-complete'
      | 'usage-gap'
      | 'session-switch'
      | 'window-blur'
      | 'window-focus';
    sessionId?: string;
    nextSessionId?: string;
  }>;
  reducedMotion?: boolean;
};

export type PastureSimulationCheckpoint = {
  scenarioId: string;
  atMs: number;
  inputContext: number | null;
  visualContext: number;
  stage: number;
  terrainBudget: number;
  plantCount: number;
  animalCount: number;
  activeMotionCount: number;
  queuedCompression: 'none' | 'start' | 'complete';
  activeSessionId: string;
  snapshotVersion: 2;
};

function isValidRatio(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}

function smoothToward(current: number, target: number): number {
  const delta = target - current;
  if (Math.abs(delta) < 0.01) return target;
  return current + Math.sign(delta) * Math.min(Math.abs(delta), Math.max(0.04, Math.abs(delta) * 0.35));
}

function countPlants(percent: number): number {
  return Math.min(30, Math.max(2, Math.round(2 + plantDensity(percent) * 28)));
}

function checkpoint(
  scenario: PastureSimulationScenario,
  atMs: number,
  inputContext: number | null,
  visualContext: number,
  activeSessionId: string,
  queuedCompression: 'none' | 'start' | 'complete',
  motionEnabled: boolean,
): PastureSimulationCheckpoint {
  const percent = Math.min(100, Math.max(0, visualContext));
  const modeMotion = queuedCompression === 'none' && motionEnabled;
  return {
    scenarioId: scenario.id,
    atMs,
    inputContext,
    visualContext: percent,
    stage: stageForPercent(percent).id,
    terrainBudget: Math.round(2 + percent * 0.28),
    plantCount: countPlants(percent),
    animalCount: modeMotion ? animalBudget(percent) : Math.min(1, animalBudget(percent)),
    activeMotionCount: scenario.reducedMotion || !modeMotion ? 0 : Math.min(3, 1 + Math.floor(percent / 50)),
    queuedCompression,
    activeSessionId,
    snapshotVersion: 2,
  };
}

/**
 * 仅供开发/测试使用的确定性生态检查器。它不读取生产数据、不写入存储，
 * 也不被 ContextPasture 组件导入，因此不会进入生产运行时生命周期。
 */
export function simulatePastureScenario(
  scenario: PastureSimulationScenario,
): PastureSimulationCheckpoint[] {
  const sequence = [...scenario.contextSequence].sort((a, b) => a.atMs - b.atMs);
  const events = [...scenario.events].sort((a, b) => a.atMs - b.atMs);
  const times = Array.from(new Set([
    ...sequence.map(item => item.atMs),
    ...events.map(item => item.atMs),
  ])).sort((a, b) => a - b);
  const checkpoints: PastureSimulationCheckpoint[] = [];
  let activeSessionId = scenario.sessionId;
  let visualContext = 0;
  let lastReliableContext: number | null = null;
  let queuedCompression: 'none' | 'start' | 'complete' = 'none';
  let motionEnabled = true;
  let sequenceIndex = 0;
  let eventIndex = 0;

  for (const atMs of times) {
    let inputContext: number | null = lastReliableContext;
    let hasNewReliableSample = false;
    while (sequenceIndex < sequence.length && sequence[sequenceIndex]!.atMs <= atMs) {
      const sample = sequence[sequenceIndex]!;
      sequenceIndex += 1;
      inputContext = sample.ratio;
      if (isValidRatio(sample.ratio)) {
        lastReliableContext = sample.ratio;
        hasNewReliableSample = true;
      } else inputContext = lastReliableContext;
    }

    while (eventIndex < events.length && events[eventIndex]!.atMs <= atMs) {
      const event = events[eventIndex]!;
      eventIndex += 1;
      if (event.sessionId && event.sessionId !== activeSessionId) continue;
      if (event.type === 'compression-start') queuedCompression = 'start';
      if (event.type === 'compression-complete') queuedCompression = 'complete';
      if (event.type === 'window-blur') motionEnabled = false;
      if (event.type === 'window-focus') motionEnabled = true;
      if (event.type === 'session-switch') {
        activeSessionId = event.nextSessionId ?? activeSessionId;
        visualContext = 0;
        lastReliableContext = null;
        queuedCompression = 'none';
      }
    }

    if (hasNewReliableSample && isValidRatio(inputContext)) {
      visualContext = smoothToward(visualContext, inputContext * 100);
    }
    if (queuedCompression === 'complete') {
      queuedCompression = 'none';
    }
    checkpoints.push(checkpoint(
      scenario,
      atMs,
      isValidRatio(inputContext) ? inputContext : null,
      visualContext,
      activeSessionId,
      queuedCompression,
      motionEnabled,
    ));
  }
  return checkpoints;
}
