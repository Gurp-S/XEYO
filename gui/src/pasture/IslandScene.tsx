import type {CSSProperties} from 'react';
import {IslandCoconuts} from '@/pasture/IslandCoconuts';
import {IslandCompanion} from '@/pasture/IslandCompanion';
import {IslandStars} from '@/pasture/IslandStars';
import type {
  CharacterLocation,
  IslandCompanionMode,
  IslandCompanionVisibility,
} from '@/pasture/core/ContextIslandState';

type Props = {
  coconutCount: number;
  starCount: number;
  companionVisibility: IslandCompanionVisibility;
  companionMode: IslandCompanionMode;
  fallenCoconutCount: number;
  characterLocation: CharacterLocation;
  compressionActive: boolean;
  dark: boolean;
  reducedMotion: boolean;
  sidebarWidth: number;
  tooltip: string;
};

export function IslandScene({
  coconutCount,
  starCount,
  companionVisibility,
  companionMode,
  fallenCoconutCount,
  characterLocation,
  compressionActive,
  dark,
  reducedMotion,
  sidebarWidth,
  tooltip,
}: Props) {
  return (
    <div
      className="xy-context-island"
      data-reduced-motion={reducedMotion ? 'true' : 'false'}
      data-theme={dark ? 'dark' : 'light'}
      style={{'--island-width': `${sidebarWidth}px`} as CSSProperties}
    >
      <div className="xy-context-island__scene" aria-hidden="true">
        <div className="xy-context-island__sea xy-context-island__layer">
          <img className="xy-context-island__asset" src="/context-island/sea/wave-01.svg" alt="" />
          <img className="xy-context-island__asset" src="/context-island/sea/wave-02.svg" alt="" />
          <img className="xy-context-island__asset" src="/context-island/sea/wave-03.svg" alt="" />
          <img className="xy-context-island__asset" src="/context-island/sea/wave-04.svg" alt="" />
        </div>
        <div className="xy-context-island__foam xy-context-island__layer">
          <img className="xy-context-island__asset" src="/context-island/foam/foam-01.svg" alt="" />
          <img className="xy-context-island__asset" src="/context-island/foam/foam-02.svg" alt="" />
        </div>
        <img className="xy-context-island__base xy-context-island__base--island" src="/context-island/island.svg" alt="" />
        <div className="xy-context-island__tree-window">
          <img className="xy-context-island__tree" src="/context-island/palm-tree.svg" alt="" />
        </div>
        <IslandStars count={starCount} dark={dark} />
        <IslandCoconuts
          treeCount={compressionActive ? Math.min(2, coconutCount) : coconutCount}
          fallenCount={fallenCoconutCount}
          compressionActive={compressionActive}
          reducedMotion={reducedMotion}
        />
        <IslandCompanion
          visibility={companionVisibility}
          mode={companionMode}
          location={characterLocation}
          reducedMotion={reducedMotion}
        />
      </div>
      <button
        className="xy-context-island__tooltip-anchor"
        type="button"
        aria-label={tooltip}
        data-tooltip={tooltip}
        tabIndex={0}
      />
    </div>
  );
}
