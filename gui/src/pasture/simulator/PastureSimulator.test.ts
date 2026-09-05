import {describe, expect, it} from 'vitest';
import {simulatePastureScenario, type PastureSimulationScenario} from './PastureSimulator';

function scenario(partial: Partial<PastureSimulationScenario>): PastureSimulationScenario {
  return {
    id: 'test',
    sessionId: 'session-a',
    seed: 'seed-a',
    contextSequence: [],
    events: [],
    ...partial,
  };
}

describe('PastureSimulator', () => {
  it('keeps seed-0 sparse and does not invent animals', () => {
    const [checkpoint] = simulatePastureScenario(scenario({
      id: 'seed-0',
      contextSequence: [{atMs: 0, ratio: null}],
    }));
    expect(checkpoint).toMatchObject({
      visualContext: 0,
      stage: 0,
      animalCount: 0,
      plantCount: 2,
      activeMotionCount: 1,
    });
  });

  it('approaches growth in steps instead of filling the pasture in one frame', () => {
    const checkpoints = simulatePastureScenario(scenario({
      id: 'growth-0-to-100',
      contextSequence: [
        {atMs: 0, ratio: 0},
        {atMs: 100, ratio: 1},
        {atMs: 200, ratio: 1},
      ],
    }));
    expect(checkpoints[0]!.visualContext).toBe(0);
    expect(checkpoints[1]!.visualContext).toBeLessThan(100);
    expect(checkpoints[2]!.visualContext).toBeGreaterThan(checkpoints[1]!.visualContext);
    expect(checkpoints[2]!.animalCount).toBeLessThanOrEqual(10);
  });

  it('retains the last reliable value when telemetry is missing or invalid', () => {
    const checkpoints = simulatePastureScenario(scenario({
      id: 'missing-and-invalid',
      contextSequence: [
        {atMs: 0, ratio: 0.6},
        {atMs: 100, ratio: null},
        {atMs: 200, ratio: -1},
        {atMs: 300, ratio: Number.NaN},
      ],
    }));
    expect(checkpoints[1]!.visualContext).toBe(checkpoints[0]!.visualContext);
    expect(checkpoints[2]!.visualContext).toBe(checkpoints[1]!.visualContext);
    expect(checkpoints[3]!.visualContext).toBe(checkpoints[2]!.visualContext);
  });

  it('reduces motion and animal presence during compression, then recovers after completion', () => {
    const checkpoints = simulatePastureScenario(scenario({
      id: 'compression-high-to-low',
      contextSequence: [
        {atMs: 0, ratio: 0.9},
        {atMs: 100, ratio: 0.9},
        {atMs: 200, ratio: 0.2},
      ],
      events: [
        {atMs: 100, type: 'compression-start', sessionId: 'session-a'},
        {atMs: 200, type: 'compression-complete', sessionId: 'session-a'},
      ],
    }));
    expect(checkpoints[1]!.queuedCompression).toBe('start');
    expect(checkpoints[1]!.animalCount).toBeLessThanOrEqual(1);
    expect(checkpoints[2]!.queuedCompression).toBe('none');
  });

  it('stops high-cost motion while blurred and does not replay it on focus', () => {
    const checkpoints = simulatePastureScenario(scenario({
      id: 'blur-focus-reduced-motion',
      reducedMotion: true,
      contextSequence: [{atMs: 0, ratio: 0.8}, {atMs: 100, ratio: 0.9}],
      events: [
        {atMs: 100, type: 'window-blur'},
        {atMs: 200, type: 'window-focus'},
      ],
    }));
    expect(checkpoints.every(item => item.activeMotionCount === 0)).toBe(true);
  });

  it('isolates session switches from the outgoing session snapshot', () => {
    const checkpoints = simulatePastureScenario(scenario({
      id: 'switch-between-sessions',
      contextSequence: [{atMs: 0, ratio: 0.8}, {atMs: 100, ratio: 0.1}],
      events: [{atMs: 100, type: 'session-switch', nextSessionId: 'session-b'}],
    }));
    expect(checkpoints[0]!.activeSessionId).toBe('session-a');
    expect(checkpoints[1]!.activeSessionId).toBe('session-b');
    expect(checkpoints[1]!.visualContext).toBeLessThan(checkpoints[0]!.visualContext);
  });
});
