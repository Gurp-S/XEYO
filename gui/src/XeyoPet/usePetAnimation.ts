import {useEffect, useState} from 'react';
import type {PetStateRow} from './types';

const DEFAULT_FPS = 6;

export function usePetAnimation(
  stateRow: PetStateRow,
  reducedMotion = false,
): number {
  const {state, row, frames, frameSequence, fps, loop} = stateRow;
  const frameCount = frameSequence?.length ?? frames;
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    setFrame(0);
    if (reducedMotion || frameCount <= 1) return;

    const intervalMs = Math.max(80, Math.round(1000 / (fps ?? DEFAULT_FPS)));
    const timer = window.setInterval(() => {
      setFrame(current => {
        const next = current + 1;
        if (next < frameCount) return next;
        return loop === false ? frameCount - 1 : 0;
      });
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [frameCount, fps, loop, reducedMotion, row, state]);

  return Math.min(Math.max(frame, 0), Math.max(0, frameCount - 1));
}
