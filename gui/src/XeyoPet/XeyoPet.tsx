import type {CSSProperties} from 'react';

import {getPetBubbleUrl, getPetStateRow, resolvePetState} from './PetManifest';
import {usePetAnimation} from './usePetAnimation';
import type {LoadedPetManifest} from './types';
import type {PetFacing} from '@/pet/usePetFacing';

export type XeyoPetProps = {
  loaded: LoadedPetManifest;
  state?: string;
  reducedMotion?: boolean;
  facing?: PetFacing;
  className?: string;
  label?: string;
};

export function XeyoPet({
  loaded,
  state,
  reducedMotion = false,
  facing = 'left',
  className,
  label = loaded.manifest.displayName,
}: XeyoPetProps) {
  const {manifest} = loaded;
  const resolvedState = resolvePetState(loaded, state);
  const row = getPetStateRow(loaded, resolvedState);
  const bubbleUrl = getPetBubbleUrl(loaded, resolvedState);
  const {width, height} = manifest.cellSize;
  const cols = manifest.columns;
  const logicalFrame = usePetAnimation(row, reducedMotion);
  const atlasFrame = row.frameSequence?.[logicalFrame] ?? logicalFrame;
  const isIdle = resolvedState === 'idle';
  const isBubbleOnly = row.animationMode === 'bubble-only' && row.animationRegion !== undefined;
  const showIdleBlink = isIdle && atlasFrame === 4;

  // Render the complete frozen cell. Its transparent margins already isolate
  // the hair from neighboring atlas frames, so no inner crop is applied.
  const edgeGuard = 0;
  const baseFrame = isIdle || isBubbleOnly ? row.frameSequence?.[0] ?? 0 : atlasFrame;
  const baseFrameOffsetX = row.frameOffsetsX?.[baseFrame] ?? 0;

  const atlasStyle = (frame: number, offsetX: number): CSSProperties => ({
    position: 'absolute',
    left: edgeGuard,
    top: edgeGuard,
    width: width - edgeGuard * 2,
    height: height - edgeGuard * 2,
    overflow: 'hidden',
    backgroundImage: `url(${loaded.sheetUrl})`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${width * cols}px ${height * manifest.rows}px`,
    backgroundPosition: `${-(frame * width + offsetX + edgeGuard)}px ${-(row.row * height + edgeGuard)}px`,
  });

  const style = atlasStyle(baseFrame, baseFrameOffsetX);
  const animationRegion = row.animationRegion;
  const bubbleOnlyBaseStyle: CSSProperties = isBubbleOnly
    ? {
        ...style,
        // The mask removes only the baked bubble pixels; the full character remains intact.
        WebkitMaskImage: 'url(/XeyoPet/sleeping-character-mask.png)',
        maskImage: 'url(/XeyoPet/sleeping-character-mask.png)',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskSize: `${width}px ${height}px`,
        maskSize: `${width}px ${height}px`,
        WebkitMaskPosition: '0 0',
        maskPosition: '0 0',
      }
    : style;
  const baseStyles: CSSProperties[] = [bubbleOnlyBaseStyle];
  const localizedAnimationStyle: CSSProperties | undefined = isBubbleOnly && animationRegion
    ? {
        ...atlasStyle(atlasFrame, row.frameOffsetsX?.[atlasFrame] ?? 0),
        // This is the only layer that paints the current sleeping bubble.
        WebkitMaskImage: 'url(/XeyoPet/sleeping-bubble-mask-strip.png)',
        maskImage: 'url(/XeyoPet/sleeping-bubble-mask-strip.png)',
        WebkitMaskRepeat: 'no-repeat',
        maskRepeat: 'no-repeat',
        WebkitMaskSize: `${width * 6}px ${height}px`,
        maskSize: `${width * 6}px ${height}px`,
        WebkitMaskPosition: `${-(atlasFrame * width)}px 0`,
        maskPosition: `${-(atlasFrame * width)}px 0`,
      }
    : undefined;
  const blinkStyle: CSSProperties = {
    ...atlasStyle(4, row.frameOffsetsX?.[4] ?? 0),
    // Frame 4's eye band is 12px left and 2px lower than frame 0. Keep the
    // clip narrow so no face contour or hair from frame 4 enters the base.
    transform: 'translate3d(12px, -2px, 0)',
    clipPath: 'inset(62px 52px 116px 54px)',
  };

  return (
    <div
      className={className ? `xeyo-pet__sprite ${className}` : 'xeyo-pet__sprite'}
      data-pet-state={resolvedState}
      data-pet-row={row.row}
      data-pet-motion={row.animationMode ?? 'frame'}
      data-pet-facing={facing}
      data-reduced-motion={reducedMotion ? 'true' : 'false'}
      aria-label={label}
      role="img"
    >
      <div className="xeyo-pet__art" data-pet-facing={facing} aria-hidden>
      {baseStyles.map((baseStyle, index) => (
        <div
          className="xeyo-pet__atlas"
          style={baseStyle}
          data-pet-frame={baseFrame}
          data-pet-layer={index === 0 ? 'base' : 'base-segment'}
          aria-hidden
          key={`base-${index}`}
        />
      ))}

      {showIdleBlink ? (
        <div
          className="xeyo-pet__idle-blink"
          style={blinkStyle}
          aria-hidden
        />
      ) : null}

      {localizedAnimationStyle ? (
        <div
          className="xeyo-pet__localized-atlas"
          data-pet-motion={row.animationMode}
          data-pet-layer="localized"
          style={localizedAnimationStyle}
          aria-hidden
        />
      ) : null}
      </div>

      {bubbleUrl ? (
        <img
          className="xeyo-pet__bubble"
          data-pet-layer="external"
          key={bubbleUrl}
          src={bubbleUrl}
          alt=""
          aria-hidden
          draggable={false}
        />
      ) : null}
    </div>
  );
}
