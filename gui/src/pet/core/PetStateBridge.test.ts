import {describe, expect, it} from 'vitest';
import type {PetContextPayload} from '@/pet/PetBridge';
import {stateForLegacyMode, stateForPetContext} from './PetStateBridge';

function payload(
  snapshot: PetContextPayload['snapshot'],
): PetContextPayload {
  return {sessionId: 'test-session', snapshot, location: 'desktop'};
}

describe('XeyoPet state bridge', () => {
  it('maps active agent states to thinking', () => {
    expect(stateForPetContext(payload({agentState: 'thinking'}))).toBe('thinking');
    expect(stateForPetContext(payload({agentState: 'tooling'}))).toBe('thinking');
    expect(stateForPetContext(payload({agentState: 'browser'}))).toBe('thinking');
    expect(stateForPetContext(payload({agentState: 'coding'}))).toBe('thinking');
  });

  it('maps completion, failure and compression without changing the source event', () => {
    expect(stateForPetContext(payload({agentState: 'success'}))).toBe('happy');
    expect(stateForPetContext(payload({agentState: 'error'}))).toBe('failed');
    expect(
      stateForPetContext(payload({agentState: 'idle', compressionState: 'compressing'})),
    ).toBe('sleeping');
  });

  it('keeps quiet low-usage and normal idle states distinct', () => {
    expect(stateForPetContext(payload({agentState: 'idle', usagePercent: 3}))).toBe('sleeping');
    expect(stateForPetContext(payload({agentState: 'idle', usagePercent: 32}))).toBe('idle');
  });

  it('supports legacy island companion modes as a compatibility bridge', () => {
    expect(stateForLegacyMode('idle')).toBe('idle');
    expect(stateForLegacyMode('thinking')).toBe('thinking');
    expect(stateForLegacyMode('react')).toBe('happy');
    expect(stateForLegacyMode('compression')).toBe('sleeping');
    expect(stateForLegacyMode('alert')).toBe('failed');
    expect(stateForLegacyMode('empty')).toBe('waiting');
  });
});
