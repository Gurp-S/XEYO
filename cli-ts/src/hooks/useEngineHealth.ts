import { useCallback, useEffect, useState } from "react";
import { healthOk } from "../api/sse.js";

/** Poll engine /health; null = checking. */
export function useEngineHealth(baseUrl: string, intervalMs = 8000) {
  const [connected, setConnected] = useState<boolean | null>(null);

  const refresh = useCallback(async (): Promise<boolean> => {
    const ok = await healthOk(baseUrl);
    setConnected(ok);
    return ok;
  }, [baseUrl]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const ok = await healthOk(baseUrl);
      if (alive) setConnected(ok);
    };
    void tick();
    const id = setInterval(() => void tick(), intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [baseUrl, intervalMs]);

  return { connected, refresh };
}
