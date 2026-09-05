import {useCallback, useEffect, useRef, useState} from 'react';
import type {Monitor, Window as TauriWindow} from '@tauri-apps/api/window';

export type PetFacing = 'left' | 'right';

type PetWindow = Pick<TauriWindow, 'outerPosition' | 'outerSize' | 'onMoved'>;

const DEFAULT_FACING: PetFacing = 'left';
export const PET_FACING_DEAD_ZONE_PX = 72;

export function resolvePetFacing(
  petCenterX: number,
  monitorCenterX: number,
  previousFacing: PetFacing = DEFAULT_FACING,
  deadZonePx = PET_FACING_DEAD_ZONE_PX,
): PetFacing {
  const distanceFromCenter = petCenterX - monitorCenterX;
  if (distanceFromCenter < -deadZonePx) return 'right';
  if (distanceFromCenter > deadZonePx) return 'left';
  return previousFacing;
}

/**
 * Keeps the pet looking toward the horizontal center of the monitor it is on.
 * The dead zone prevents rapid left/right flipping while crossing the center.
 */
export function usePetFacing(): PetFacing {
  const [facing, setFacing] = useState<PetFacing>(DEFAULT_FACING);
  const isReadingPosition = useRef(false);
  const lastFacing = useRef<PetFacing>(DEFAULT_FACING);

  const refreshFacing = useCallback(async (windowHandle: PetWindow, readMonitor: () => Promise<Monitor | null>) => {
    if (isReadingPosition.current) return;
    isReadingPosition.current = true;
    try {
      const [position, size, monitor] = await Promise.all([
        windowHandle.outerPosition(),
        windowHandle.outerSize(),
        readMonitor(),
      ]);
      if (!monitor) return;

      const petCenterX = position.x + size.width / 2;
      const monitorCenterX = monitor.workArea.position.x + monitor.workArea.size.width / 2;
      const nextFacing = resolvePetFacing(petCenterX, monitorCenterX, lastFacing.current);

      if (nextFacing !== lastFacing.current) {
        lastFacing.current = nextFacing;
        setFacing(nextFacing);
      }
    } catch {
      // Browser previews and early window startup may not expose position APIs.
    } finally {
      isReadingPosition.current = false;
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window)) return;

    let disposed = false;
    let unlistenMoved: (() => void) | undefined;
    let currentWindow: PetWindow | undefined;

    void import('@tauri-apps/api/window')
      .then(async ({currentMonitor, getCurrentWindow}) => {
        if (disposed) return;
        currentWindow = getCurrentWindow();
        await refreshFacing(currentWindow, currentMonitor);
        if (disposed || !currentWindow) return;
        unlistenMoved = await currentWindow.onMoved(() => {
          if (currentWindow) void refreshFacing(currentWindow, currentMonitor);
        });
      })
      .catch(() => undefined);

    return () => {
      disposed = true;
      unlistenMoved?.();
      currentWindow = undefined;
    };
  }, [refreshFacing]);

  return facing;
}
