import {describe, expect, it} from 'vitest';

import {PET_FACING_DEAD_ZONE_PX, resolvePetFacing} from './usePetFacing';

describe('resolvePetFacing', () => {
  it('faces right when the pet is left of the monitor center', () => {
    expect(resolvePetFacing(400, 960)).toBe('right');
  });

  it('faces left when the pet is right of the monitor center', () => {
    expect(resolvePetFacing(1520, 960)).toBe('left');
  });

  it('keeps the previous facing inside the center dead zone', () => {
    expect(resolvePetFacing(960 - PET_FACING_DEAD_ZONE_PX + 1, 960, 'left')).toBe('left');
    expect(resolvePetFacing(960 + PET_FACING_DEAD_ZONE_PX - 1, 960, 'right')).toBe('right');
  });

  it('changes direction only after crossing the dead-zone boundary', () => {
    expect(resolvePetFacing(960 - PET_FACING_DEAD_ZONE_PX - 1, 960, 'left')).toBe('right');
    expect(resolvePetFacing(960 + PET_FACING_DEAD_ZONE_PX + 1, 960, 'right')).toBe('left');
  });
});
