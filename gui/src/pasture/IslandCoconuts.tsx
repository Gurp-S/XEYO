type Props = {
  treeCount: number;
  fallenCount: number;
  compressionActive: boolean;
  reducedMotion?: boolean;
};

const TREE_SLOTS = [1, 2, 3, 4] as const;

export function IslandCoconuts({
  treeCount,
  fallenCount,
  compressionActive,
  reducedMotion = false,
}: Props) {
  const safeTreeCount = Math.min(4, Math.max(0, treeCount));
  const groundCount = Math.min(2, Math.max(0, fallenCount));
  return (
    <div className={`xy-context-island__coconuts${compressionActive ? ' is-compressing' : ''}`} aria-hidden>
      {TREE_SLOTS.map((slot, index) => (
        <img
          key={`tree-coconut-${slot}`}
          className={`xy-context-island__coconut xy-context-island__coconut--tree-${slot}${
            index < safeTreeCount ? ' is-visible' : ''
          }`}
          src="/context-island/coconut.svg"
          alt=""
          style={reducedMotion ? {transitionDelay: '0s'} : {transitionDelay: `${index * 0.15}s`}}
        />
      ))}
      {[1, 2].map(slot => (
        <img
          key={`ground-coconut-${slot}`}
          className={`xy-context-island__coconut xy-context-island__coconut--ground-${slot}${
            slot <= groundCount ? ' is-visible' : ''
          }`}
          src="/context-island/coconut.svg"
          alt=""
          style={reducedMotion ? {transitionDelay: '0s'} : {transitionDelay: `${slot * 0.15}s`}}
        />
      ))}
    </div>
  );
}
