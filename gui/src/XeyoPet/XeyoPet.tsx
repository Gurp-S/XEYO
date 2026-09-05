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

  // 渲染完整的冻结单元格。其透明边距已将
  // 发丝与相邻图集帧隔开，因此无需再做内部裁剪。
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
        // 遮罩只移除烘焙进图集的气泡像素；角色本身保持完整。
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
        // 只有这一层负责绘制当前的睡觉气泡。
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
    // 第 4 帧的眼带比第 0 帧左移 12px、下移 2px。裁剪
    // 保持收窄，避免第 4 帧的脸部轮廓或发丝混入底层。
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
