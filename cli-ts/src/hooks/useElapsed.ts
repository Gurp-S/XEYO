import { useEffect, useState } from "react";

/** Elapsed seconds while `active` is true. */
export function useElapsed(active: boolean): number {
  const [sec, setSec] = useState(0);

  useEffect(() => {
    if (!active) {
      setSec(0);
      return;
    }
    setSec(0);
    const started = Date.now();
    const id = setInterval(() => {
      setSec(Math.floor((Date.now() - started) / 1000));
    }, 250);
    return () => clearInterval(id);
  }, [active]);

  return sec;
}

export function formatElapsed(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m${s.toString().padStart(2, "0")}s`;
}
