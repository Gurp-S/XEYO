import type {CSSProperties} from 'react';
import {MAX_STARS} from '@/pasture/core/ContextIslandState';

type StarKind = 'medium' | 'small' | 'sparkle' | 'dot';

type StarPoint = {
  id: string;
  kind: StarKind;
  left: string;
  top: string;
  size: string;
  opacity: number;
};

const STAR_POINTS: readonly StarPoint[] = [
  {id: 'star-01', kind: 'sparkle', left: '14%', top: '15%', size: '15px', opacity: 0.82},
  {id: 'star-02', kind: 'small', left: '29%', top: '11%', size: '9px', opacity: 0.7},
  {id: 'star-03', kind: 'dot', left: '42%', top: '19%', size: '6px', opacity: 0.64},
  {id: 'star-04', kind: 'medium', left: '57%', top: '10%', size: '13px', opacity: 0.78},
  {id: 'star-05', kind: 'small', left: '69%', top: '22%', size: '8px', opacity: 0.66},
  {id: 'star-06', kind: 'dot', left: '82%', top: '13%', size: '5px', opacity: 0.6},
  {id: 'star-07', kind: 'small', left: '21%', top: '32%', size: '8px', opacity: 0.62},
  {id: 'star-08', kind: 'sparkle', left: '38%', top: '33%', size: '12px', opacity: 0.75},
  {id: 'star-09', kind: 'dot', left: '53%', top: '29%', size: '5px', opacity: 0.6},
  {id: 'star-10', kind: 'medium', left: '73%', top: '37%', size: '12px', opacity: 0.74},
  {id: 'star-11', kind: 'small', left: '87%', top: '29%', size: '9px', opacity: 0.66},
  {id: 'star-12', kind: 'dot', left: '63%', top: '48%', size: '5px', opacity: 0.58},
];

const STAR_SRC: Record<StarKind, string> = {
  medium: '/context-island/stars/star-medium.svg',
  small: '/context-island/stars/star-small.svg',
  sparkle: '/context-island/stars/sparkle.svg',
  dot: '/context-island/stars/star-dot.svg',
};

export function IslandStars({count, dark}: {count: number; dark: boolean}) {
  const visibleCount = Math.min(MAX_STARS, Math.max(0, count));
  return (
    <div className={`xy-context-island__stars${dark ? ' is-dark' : ''}`} aria-hidden>
      {STAR_POINTS.map((star, index) => {
        const style = {
          left: star.left,
          top: star.top,
          '--star-size': star.size,
          '--star-opacity': star.opacity,
        } as CSSProperties;
        return (
          <img
            key={star.id}
            className={`xy-context-island__star${index < visibleCount ? ' is-visible' : ''}`}
            src={STAR_SRC[star.kind]}
            alt=""
            style={style}
          />
        );
      })}
    </div>
  );
}
