import type {PetContextPayload} from '@/pet/PetBridge';
import type {IslandCompanionMode} from '@/pasture/core/ContextIslandState';

export const PET_STATES = [
  'idle',
  'running',
  'thinking',
  'waiting',
  'happy',
  'failed',
  'review',
  'sleeping',
  'waving',
  'sitting',
] as const;

export type PetState = (typeof PET_STATES)[number];

export function stateForLegacyMode(mode: IslandCompanionMode | null | undefined): PetState {
  switch (mode) {
    case 'thinking':
      return 'thinking';
    case 'happy':
    case 'react':
      return 'happy';
    case 'compression':
    case 'sleep':
      return 'sleeping';
    case 'alert':
      return 'failed';
    case 'empty':
      return 'waiting';
    case 'idle':
    default:
      return 'idle';
  }
}

export function stateForPetContext(payload: PetContextPayload): PetState {
  const snapshot = payload.snapshot;
  const compressionState = snapshot.compressionState;
  if (compressionState === 'compressing') return 'sleeping';

  switch (snapshot.agentState) {
    case 'thinking':
    case 'tooling':
    case 'browser':
    case 'coding':
      return 'thinking';
    case 'success':
      return 'happy';
    case 'error':
      return 'failed';
    case 'idle':
    default:
      break;
  }

  const usagePercent = snapshot.usagePercent;
  if (typeof usagePercent === 'number' && Number.isFinite(usagePercent) && usagePercent <= 5) {
    return 'sleeping';
  }
  return 'idle';
}
