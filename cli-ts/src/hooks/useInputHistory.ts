import { useCallback, useState } from "react";

/** Arrow-up / arrow-down through prior submissions. */
export function useInputHistory(limit = 50) {
  const [history, setHistory] = useState<string[]>([]);
  const [cursor, setCursor] = useState(-1);
  const [draft, setDraft] = useState("");

  const push = useCallback(
    (line: string) => {
      const t = line.trim();
      if (!t) return;
      setHistory((h) => {
        if (h[0] === t) return h;
        return [t, ...h].slice(0, limit);
      });
      setCursor(-1);
      setDraft("");
    },
    [limit],
  );

  const beginNav = useCallback(
    (current: string) => {
      if (cursor < 0) setDraft(current);
    },
    [cursor],
  );

  const older = useCallback(
    (current: string): string | null => {
      if (history.length === 0) return null;
      beginNav(current);
      const next = Math.min(cursor + 1, history.length - 1);
      setCursor(next);
      return history[next] ?? null;
    },
    [beginNav, cursor, history],
  );

  const newer = useCallback(
    (current: string): string | null => {
      if (cursor < 0) return null;
      beginNav(current);
      const next = cursor - 1;
      if (next < 0) {
        setCursor(-1);
        return draft;
      }
      setCursor(next);
      return history[next] ?? draft;
    },
    [beginNav, cursor, draft, history],
  );

  const resetNav = useCallback(() => {
    setCursor(-1);
    setDraft("");
  }, []);

  return { push, older, newer, resetNav, cursor };
}
