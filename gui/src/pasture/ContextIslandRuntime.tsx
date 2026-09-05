import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {useLocation} from 'react-router-dom';
import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore} from '@/stores/settingsStore';
import {isDarkScheme} from '@/theme/catalog';
import {
  consumePendingCompression,
  listenPastureEvents,
  type PastureEventDetail,
} from '@/pasture/events/PastureEvents';
import {forwardContextToPet, invokePet} from '@/pet/PetBridge';
import {isTauri} from '@/lib/tauri';
import {
  deriveIslandState,
  eventModeForAgentState,
  percentOf,
  shouldTriggerReaction,
  tooltipForIsland,
  type IslandCompanionMode,
} from '@/pasture/core/ContextIslandState';
import {
  normalizeContextSnapshot,
  snapshotFromUsage,
  type ContextSnapshot,
} from '@/pasture/context/ContextStage';
import {IslandScene} from '@/pasture/IslandScene';
import {useViewport} from '@/hooks/useViewport';
import '@/pasture/animation/context-island.css';

function eventSessionMatches(eventSessionId: string | undefined, activeSessionId: string | null): boolean {
  return !eventSessionId || eventSessionId === activeSessionId;
}

function modeFromAgentEvent(event: string): IslandCompanionMode | null {
  const value = event.toLowerCase();
  if (/error|fail|exception|abort/.test(value)) return 'alert';
  if (/success|complete|done|finish/.test(value)) return 'happy';
  if (/think|tool|browser|code|working/.test(value)) return 'thinking';
  return null;
}

export function ContextIslandRuntime() {
  const location = useLocation();
  const activeId = useChatStore(state => state.activeId);
  const sidebarOpen = useChatStore(state => state.sidebarOpen);
  const sessionUsage = useChatStore(state => (activeId ? state.sessionUsageById[activeId] : null));
  const sidebarWidth = useSettingsStore(state => state.sidebarWidth);
  const pastureEnabled = useSettingsStore(state => state.pastureEnabled);
  const pastureReducedMotion = useSettingsStore(state => state.pastureReducedMotion);
  const pasturePaused = useSettingsStore(state => state.pasturePaused);
  const configuredTheme = useSettingsStore(state => state.theme);
  const [snapshot, setSnapshot] = useState<ContextSnapshot>(() => snapshotFromUsage(sessionUsage));
  const [compressionActive, setCompressionActive] = useState(false);
  const [eventMode, setEventMode] = useState<IslandCompanionMode | null>(null);
  const [preview, setPreview] = useState<{percent: number | null; compress: boolean}>({
    percent: null,
    compress: false,
  });
  const [detached, setDetached] = useState(false);
  const [petStatus, setPetStatus] = useState('');
  const [dark, setDark] = useState(() => {
    if (typeof document === 'undefined') return isDarkScheme(configuredTheme);
    return (
      isDarkScheme(configuredTheme) ||
      document.documentElement.dataset.scheme === 'dark'
    );
  });
  const transientTimer = useRef<number | null>(null);
  const {compact} = useViewport();
  const isDev = import.meta.env.DEV;

  const flashMode = useCallback((mode: IslandCompanionMode | null, duration = 1800) => {
    if (transientTimer.current !== null) {
      window.clearTimeout(transientTimer.current);
      transientTimer.current = null;
    }
    setEventMode(mode);
    if (!mode || mode === 'idle' || duration <= 0) return;
    transientTimer.current = window.setTimeout(() => {
      setEventMode(null);
      transientTimer.current = null;
    }, duration);
  }, []);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const updateTheme = () => {
      setDark(
        isDarkScheme(configuredTheme) ||
          document.documentElement.dataset.scheme === 'dark',
      );
    };
    updateTheme();
    const observer = new MutationObserver(updateTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'data-scheme', 'class'],
    });
    return () => observer.disconnect();
  }, [configuredTheme]);

  useEffect(() => {
    if (pasturePaused) return;
    const base = snapshotFromUsage(sessionUsage);
    setSnapshot(base);
    setCompressionActive(base.compressionState === 'compressing');
    setEventMode(eventModeForAgentState(base.agentState));
    if (activeId) {
      const pending = consumePendingCompression(activeId);
      if (pending?.phase === 'start') {
        setCompressionActive(true);
        flashMode('compression', 2200);
      } else if (pending?.phase === 'complete') {
        const next = normalizeContextSnapshot({...base, ...(pending.snapshot ?? {}), compressionState: 'complete'});
        setSnapshot(next);
        setCompressionActive(false);
        flashMode(typeof next.usagePercent === 'number' && next.usagePercent < 20 ? 'sleep' : null, 2200);
      }
    }
  }, [activeId, sessionUsage, pasturePaused, flashMode]);

  useEffect(() => {
    if (pasturePaused) return;
    return listenPastureEvents((detail: PastureEventDetail) => {
      if (!eventSessionMatches(detail.sessionId, activeId)) return;
      if (detail.type === 'CONTEXT_UPDATE') {
        setSnapshot(current => normalizeContextSnapshot({...current, ...detail.snapshot}));
        if (detail.snapshot.compressionState === 'compressing') {
          setCompressionActive(true);
          flashMode('compression', 2200);
        }
        return;
      }
      if (detail.type === 'CONTEXT_COMPRESSION_START') {
        setCompressionActive(true);
        flashMode('compression', 2200);
        return;
      }
      if (detail.type === 'CONTEXT_COMPRESSION_COMPLETE') {
        setCompressionActive(false);
        setSnapshot(current => {
          const next = normalizeContextSnapshot({...current, ...(detail.snapshot ?? {}), compressionState: 'complete'});
          flashMode(typeof next.usagePercent === 'number' && next.usagePercent < 20 ? 'sleep' : null, 2200);
          return next;
        });
        return;
      }
      if (detail.type === 'AGENT_STATE') {
        setSnapshot(current => normalizeContextSnapshot({...current, agentState: detail.state}));
        flashMode(eventModeForAgentState(detail.state));
        return;
      }
      if (detail.type === 'AGENT_EVENT') {
        const mode = modeFromAgentEvent(detail.event);
        if (mode) flashMode(mode);
      }
    });
  }, [activeId, pasturePaused, flashMode]);

  useEffect(() => () => {
    if (transientTimer.current !== null) window.clearTimeout(transientTimer.current);
  }, []);

  const effectiveSnapshot = useMemo<ContextSnapshot>(() => {
    if (preview.percent === null && !preview.compress) return snapshot;
    return normalizeContextSnapshot({
      ...snapshot,
      usagePercent: preview.percent ?? snapshot.usagePercent,
      compressionState: preview.compress ? 'compressing' : snapshot.compressionState,
    });
  }, [snapshot, preview]);

  const derived = useMemo(
    () =>
      deriveIslandState(effectiveSnapshot, {
        compressionActive: compressionActive || preview.compress,
        alertActive: eventMode === 'alert',
        eventMode,
      }),
    [effectiveSnapshot, compressionActive, preview.compress, eventMode],
  );

  const prevUsageRef = useRef(percentOf(effectiveSnapshot));
  useEffect(() => {
    const next = percentOf(effectiveSnapshot);
    const prev = prevUsageRef.current;
    if (prev !== next) {
      if (shouldTriggerReaction(prev, next) && derived.companionVisibility !== 'hidden') {
        flashMode('react', 1500);
      }
      prevUsageRef.current = next;
    }
  }, [effectiveSnapshot.usagePercent, derived.companionVisibility, flashMode]);

  // 让桌面宠物与当前语境投影保持同步。
  useEffect(() => {
    void forwardContextToPet({
      sessionId: activeId,
      snapshot: effectiveSnapshot,
      location: detached ? 'desktop' : derived.characterLocation,
    });
  }, [activeId, effectiveSnapshot, derived.characterLocation, detached]);

  if (!pastureEnabled || !sidebarOpen) return null;

  const visibleSidebarWidth = compact ? Math.min(sidebarWidth, 280) : sidebarWidth;

  const setLevel = (percent: number) =>
    setPreview(current => ({...current, percent: current.percent === percent ? null : percent}));
  const releasePet = async () => {
    if (!isTauri()) {
      setPetStatus('浏览器环境：请在桌面 App 中使用');
      return;
    }
    try {
      await invokePet('character_lift', {x: 220, y: 200});
      setDetached(true);
      setPetStatus('桌宠已放出');
    } catch (error) {
      setPetStatus(`放出失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };
  const recallPet = async () => {
    try {
      await invokePet('character_drop_on_island');
      setDetached(false);
      setPetStatus('已收回桌宠');
    } catch (error) {
      setPetStatus(`收回失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const tooltip = tooltipForIsland(effectiveSnapshot, compressionActive || preview.compress, eventMode);
  const displayVisibility = detached ? 'hidden' : derived.companionVisibility;
  const displayLocation = detached ? 'desktop' : derived.characterLocation;

  return (
    <>
      {isDev && location.pathname.startsWith('/bench') ? (
        <div
          className="xy-island-dev"
          style={{
            position: 'fixed',
            top: 8,
            right: 12,
            zIndex: 9999,
            display: 'flex',
            gap: 4,
            alignItems: 'center',
            fontSize: 12,
          }}
        >
          <span style={{opacity: 0.7}}>预览</span>
          {[0, 25, 50, 60, 75, 90, 100].map(percent => (
            <button
              key={percent}
              type="button"
              onClick={() => setLevel(percent)}
              style={{
                padding: '2px 6px',
                border: 0,
                borderRadius: 4,
                cursor: 'pointer',
                background: preview.percent === percent ? '#2563eb' : 'rgba(0,0,0,0.25)',
                color: '#fff',
              }}
            >
              {percent}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setPreview(current => ({...current, compress: !current.compress}))}
            style={{
              padding: '2px 6px',
              border: 0,
              borderRadius: 4,
              cursor: 'pointer',
              background: preview.compress ? '#b45309' : 'rgba(0,0,0,0.25)',
              color: '#fff',
            }}
          >
            压缩
          </button>
          <button
            type="button"
            onClick={detached ? recallPet : releasePet}
            style={{
              padding: '2px 6px',
              border: 0,
              borderRadius: 4,
              cursor: 'pointer',
              background: detached ? '#dc2626' : '#16a34a',
              color: '#fff',
            }}
          >
            {detached ? '收回桌宠' : '放出桌宠'}
          </button>
          <span style={{opacity: 0.75}}>{petStatus}</span>
        </div>
      ) : null}
      <IslandScene
        key={`${activeId ?? 'none'}:${location.pathname}`}
        coconutCount={derived.coconutCount}
        starCount={derived.starCount}
        companionVisibility={displayVisibility}
        companionMode={derived.companionMode}
        fallenCoconutCount={derived.fallenCoconutCount}
        characterLocation={displayLocation}
        compressionActive={compressionActive || preview.compress}
        dark={dark}
        reducedMotion={pastureReducedMotion}
        sidebarWidth={visibleSidebarWidth}
        tooltip={tooltip}
      />
    </>
  );
}
