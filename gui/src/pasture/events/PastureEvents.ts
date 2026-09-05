import type {
  AgentState,
  CompressionSource,
  ContextSnapshot,
} from '@/pasture/context/ContextStage';

export const PASTURE_EVENT = 'xy-pasture-event';

type CompressionPhase = 'start' | 'complete';

type PendingCompression = {
  phase: CompressionPhase;
  source: CompressionSource;
  snapshot?: Partial<ContextSnapshot>;
};

export type PastureEventDetail =
  | {type: 'CONTEXT_UPDATE'; sessionId?: string; snapshot: Partial<ContextSnapshot>}
  | {type: 'CONTEXT_COMPRESSION_START'; sessionId?: string; source?: CompressionSource}
  | {
      type: 'CONTEXT_COMPRESSION_COMPLETE';
      sessionId?: string;
      source?: CompressionSource;
      snapshot?: Partial<ContextSnapshot>;
    }
  | {type: 'AGENT_STATE'; sessionId?: string; state: AgentState}
  | {type: 'AGENT_EVENT'; sessionId?: string; event: string};

const pendingCompressions = new Map<string, PendingCompression>();

export function emitPastureEvent(detail: PastureEventDetail): void {
  if (detail.type === 'CONTEXT_COMPRESSION_START' || detail.type === 'CONTEXT_COMPRESSION_COMPLETE') {
    const sessionId = detail.sessionId;
    if (sessionId) {
      pendingCompressions.set(sessionId, {
        phase: detail.type === 'CONTEXT_COMPRESSION_START' ? 'start' : 'complete',
        source: detail.source ?? 'automatic',
        snapshot: detail.type === 'CONTEXT_COMPRESSION_COMPLETE' ? detail.snapshot : undefined,
      });
    }
  }
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<PastureEventDetail>(PASTURE_EVENT, {detail}));
}

export function consumePendingCompression(sessionId: string | null | undefined): PendingCompression | null {
  if (!sessionId) return null;
  const pending = pendingCompressions.get(sessionId) ?? null;
  if (pending) pendingCompressions.delete(sessionId);
  return pending;
}

export function listenPastureEvents(
  listener: (detail: PastureEventDetail) => void,
): () => void {
  if (typeof window === 'undefined') return () => {};
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<PastureEventDetail>).detail;
    if (detail) listener(detail);
  };
  window.addEventListener(PASTURE_EVENT, handler);
  return () => window.removeEventListener(PASTURE_EVENT, handler);
}
