import {describe, expect, it} from 'vitest';
import {
  companionVisibilityForPercent,
  coconutCountForPercent,
  deriveIslandState,
  eventModeForAgentState,
  fallenCoconutCountForPercent,
  resolveCompanionMode,
  shouldTriggerReaction,
  starCountForPercent,
} from '@/pasture/core/ContextIslandState';

describe('ContextIslandState', () => {
  it('maps context load to 0–4 coconuts at 25/50/75/90', () => {
    expect(coconutCountForPercent(0)).toBe(0);
    expect(coconutCountForPercent(24)).toBe(0);
    expect(coconutCountForPercent(25)).toBe(1);
    expect(coconutCountForPercent(49)).toBe(1);
    expect(coconutCountForPercent(50)).toBe(2);
    expect(coconutCountForPercent(74)).toBe(2);
    expect(coconutCountForPercent(75)).toBe(3);
    expect(coconutCountForPercent(89)).toBe(3);
    expect(coconutCountForPercent(90)).toBe(4);
    expect(coconutCountForPercent(100)).toBe(4);
  });

  it('reveals the companion at 50% and fully at 60%', () => {
    expect(companionVisibilityForPercent(49)).toBe('hidden');
    expect(companionVisibilityForPercent(50)).toBe('head');
    expect(companionVisibilityForPercent(59)).toBe('head');
    expect(companionVisibilityForPercent(60)).toBe('full');
  });

  it('adds night stars by load without exceeding the fixed point budget', () => {
    expect(starCountForPercent(0)).toBe(0);
    expect(starCountForPercent(24)).toBe(0);
    expect(starCountForPercent(25)).toBe(4);
    expect(starCountForPercent(50)).toBe(8);
    expect(starCountForPercent(75)).toBe(12);
    expect(starCountForPercent(100)).toBe(12);
  });

  it('drops coconuts to the ground while compressing', () => {
    expect(fallenCoconutCountForPercent(24)).toBe(0);
    expect(fallenCoconutCountForPercent(60)).toBe(0);
    expect(fallenCoconutCountForPercent(75)).toBe(1);
    expect(fallenCoconutCountForPercent(90)).toBe(2);
    const compressed = deriveIslandState(
      {usagePercent: 90},
      {compressionActive: true, alertActive: false, eventMode: null},
    );
    expect(compressed.fallenCoconutCount).toBe(2);
    expect(compressed.isCompressing).toBe(true);
  });

  it('fires the reaction only when crossing 75%', () => {
    expect(shouldTriggerReaction(74, 75)).toBe(true);
    expect(shouldTriggerReaction(75, 76)).toBe(false);
    expect(shouldTriggerReaction(60, 74)).toBe(false);
    expect(shouldTriggerReaction(75, 75)).toBe(false);
  });

  it('maps agent events and gives compression the highest priority', () => {
    expect(eventModeForAgentState('thinking')).toBe('thinking');
    expect(eventModeForAgentState('tooling')).toBe('thinking');
    expect(eventModeForAgentState('success')).toBe('happy');
    expect(eventModeForAgentState('error')).toBe('alert');
    expect(resolveCompanionMode({usagePercent: 80}, {compressionActive: true, alertActive: true, eventMode: 'happy'})).toBe('compression');
    expect(resolveCompanionMode({usagePercent: 80}, {compressionActive: false, alertActive: true, eventMode: 'thinking'})).toBe('alert');
    expect(resolveCompanionMode({usagePercent: 80}, {compressionActive: false, alertActive: false, eventMode: 'thinking'})).toBe('thinking');
    expect(resolveCompanionMode({usagePercent: 40}, {compressionActive: false, alertActive: false, eventMode: 'thinking'})).toBe('idle');
  });
});
