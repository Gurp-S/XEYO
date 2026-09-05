import {useCallback, useEffect, useRef, useState} from 'react';
import type {PointerEvent as ReactPointerEvent} from 'react';
import type {CharacterLocation, IslandCompanionMode} from '@/pasture/core/ContextIslandState';
import {invokePet} from '@/pet/PetBridge';
import {usePetFacing} from '@/pet/usePetFacing';
import {stateForLegacyMode} from '@/XeyoPet/PetStateBridge';
import {XeyoPet} from '@/XeyoPet/XeyoPet';
import type {LoadedPetManifest} from '@/XeyoPet/types';

const PET_EXTRACT_HOLD_MS = 2000;

type PetPlacement = 'desktop' | 'sidebar';

export function PetScene({
  loaded,
  state,
  mode,
  location,
  reducedMotion = false,
  placement = 'desktop',
  onExtract,
}: {
  loaded: LoadedPetManifest;
  state?: string;
  mode?: IslandCompanionMode;
  location: CharacterLocation;
  reducedMotion?: boolean;
  placement?: PetPlacement;
  onExtract?: () => void | Promise<void>;
}) {
  const effectiveState = state ?? stateForLegacyMode(mode);
  const detectedFacing = usePetFacing();
  const facing = placement === 'sidebar' ? 'right' : detectedFacing;
  const [interactionState, setInteractionState] = useState<string | null>(null);
  const [isHolding, setIsHolding] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const interactionTimer = useRef<number | null>(null);
  const extractTimer = useRef<number | null>(null);
  const pointerStart = useRef<{x: number; y: number; pointerId: number} | null>(null);
  const pointerDragged = useRef(false);
  const longPressTriggered = useRef(false);
  const holdStartedAt = useRef<number | null>(null);

  const displayState = interactionState ?? effectiveState;
  const isSidebarDocked = placement === 'sidebar';

  useEffect(() => {
    return () => {
      if (interactionTimer.current !== null) window.clearTimeout(interactionTimer.current);
      if (extractTimer.current !== null) window.clearTimeout(extractTimer.current);
    };
  }, []);

  const triggerInteraction = useCallback(() => {
    setInteractionState('happy');
    if (interactionTimer.current !== null) window.clearTimeout(interactionTimer.current);
    interactionTimer.current = window.setTimeout(() => {
      setInteractionState(null);
      interactionTimer.current = null;
    }, 900);
  }, []);

  const clearExtractTimer = useCallback(() => {
    if (extractTimer.current !== null) {
      window.clearTimeout(extractTimer.current);
      extractTimer.current = null;
    }
    setIsHolding(false);
  }, []);

  const triggerExtract = useCallback(() => {
    if (!isSidebarDocked || !onExtract || longPressTriggered.current) return;
    longPressTriggered.current = true;
    // 在微任务中执行回调，使同步与异步失败
    // 都能被捕获，而不依赖 pointer-up 的时机。
    void Promise.resolve()
      .then(onExtract)
      .catch(() => {
        longPressTriggered.current = false;
      });
  }, [isSidebarDocked, onExtract]);

  const beginExtractHold = useCallback(() => {
    if (!isSidebarDocked || !onExtract) return;
    clearExtractTimer();
    longPressTriggered.current = false;
    holdStartedAt.current = Date.now();
    setIsHolding(true);
    extractTimer.current = window.setTimeout(() => {
      extractTimer.current = null;
      triggerExtract();
    }, PET_EXTRACT_HOLD_MS);
  }, [clearExtractTimer, isSidebarDocked, onExtract, triggerExtract]);

  const beginDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest('button')) return;

    if (isSidebarDocked) {
      event.currentTarget.setPointerCapture?.(event.pointerId);
      beginExtractHold();
      pointerStart.current = {x: event.clientX, y: event.clientY, pointerId: event.pointerId};
      pointerDragged.current = false;
      return;
    }

    pointerStart.current = {x: event.clientX, y: event.clientY, pointerId: event.pointerId};
    pointerDragged.current = false;
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }, [beginExtractHold, isSidebarDocked]);

  const trackDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const start = pointerStart.current;
    if (!start || start.pointerId !== event.pointerId || pointerDragged.current) return;
    const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (distance < 6) return;
    pointerDragged.current = true;

    if (isSidebarDocked) {
      // 在侧栏中，手部轻微移动仍属于有效长按。
      // 不要用桌面拖拽阈值取消提取计时器。
      return;
    }
    setIsDragging(true);
    if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window)) return;

    void import('@tauri-apps/api/window')
      .then(({getCurrentWindow}) => getCurrentWindow().startDragging())
      .catch(() => undefined);
  }, [clearExtractTimer, isSidebarDocked]);

  const finishPointer = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (pointerStart.current?.pointerId !== event.pointerId) return;
    const dragged = pointerDragged.current;
    const holdElapsed = holdStartedAt.current === null ? 0 : Date.now() - holdStartedAt.current;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    clearExtractTimer();
    setIsDragging(false);
    pointerStart.current = null;
    pointerDragged.current = false;

    if (isSidebarDocked) {
      // 兜底：pointer-up 与 2s 边界处的超时发生竞争时使用。
      if (holdElapsed >= PET_EXTRACT_HOLD_MS) triggerExtract();
      if (!dragged && !longPressTriggered.current) triggerInteraction();
      longPressTriggered.current = false;
      holdStartedAt.current = null;
      return;
    }
    if (!dragged) triggerInteraction();
  }, [clearExtractTimer, isSidebarDocked, triggerExtract, triggerInteraction]);

  const returnToIsland = useCallback(() => {
    void invokePet('character_drop_on_island');
  }, []);

  return (
    <div
      className="xeyo-pet-root"
      data-pet-id={loaded.manifest.id}
      data-pet-state={displayState}
      data-pet-placement={placement}
    >
      <div
        className="xeyo-pet"
        data-location={location}
        data-pet-state={displayState}
        data-pet-facing={facing}
        data-pet-placement={placement}
      >
        <div
          className="xeyo-pet__body"
          data-pet-holding={isHolding ? 'true' : 'false'}
          data-pet-dragging={isDragging ? 'true' : 'false'}
          onPointerDown={beginDrag}
          onPointerMove={trackDrag}
          onPointerUp={finishPointer}
          onPointerCancel={finishPointer}
          aria-label={isSidebarDocked ? '点击桌宠互动，长按 2 秒取出到桌面' : '按住拖动桌面宠物'}
        >
          <XeyoPet
            loaded={loaded}
            state={displayState}
            reducedMotion={reducedMotion}
            facing={facing}
          />
          {isSidebarDocked && isHolding ? (
            <svg
              className="xeyo-pet__hold-progress"
              viewBox="0 0 44 44"
              role="progressbar"
              aria-label="正在准备取出桌宠"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={100}
            >
              <circle className="xeyo-pet__hold-progress-track" cx="22" cy="22" r="18" />
              <circle className="xeyo-pet__hold-progress-value" cx="22" cy="22" r="18" />
            </svg>
          ) : null}
        </div>
        {!isSidebarDocked ? (
          <button
            className="xeyo-pet__home"
            type="button"
            onClick={returnToIsland}
            title="隐藏桌宠"
            aria-label="隐藏桌宠"
          >
            ⌂
          </button>
        ) : null}
      </div>
    </div>
  );
}
