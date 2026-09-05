import type {
  CharacterLocation,
  IslandCompanionMode,
  IslandCompanionVisibility,
} from '@/pasture/core/ContextIslandState';

const SHEET_SRC = '/context-island/character/character.svg';
const SHEET_WIDTH = 2980;
const SHEET_HEIGHT = 1810.4165;

type Crop = {x: number; y: number; width: number; height: number};

const CROPS: Record<IslandCompanionMode, Crop> = {
  idle: {x: 0, y: 0, width: 850, height: 980},
  thinking: {x: 700, y: 1000, width: 650, height: 810},
  happy: {x: 0, y: 1000, width: 850, height: 810},
  react: {x: 0, y: 1000, width: 850, height: 810},
  compression: {x: 2350, y: 1000, width: 630, height: 810},
  sleep: {x: 2350, y: 1000, width: 630, height: 810},
  alert: {x: 0, y: 0, width: 850, height: 980},
  empty: {x: 0, y: 0, width: 850, height: 980},
};

const EMOTION_SRC: Partial<Record<IslandCompanionMode, string>> = {
  thinking: '/context-island/emotion/dots.svg',
  happy: '/context-island/emotion/heart.svg',
  react: '/context-island/emotion/heart.svg',
  compression: '/context-island/emotion/sleep.svg',
  sleep: '/context-island/emotion/sleep.svg',
  alert: '/context-island/emotion/exclamation.svg',
  empty: '/context-island/emotion/question.svg',
};

const MODE_LABEL: Record<IslandCompanionMode, string> = {
  idle: '待机',
  thinking: '思考中',
  happy: '任务完成',
  react: '开心',
  compression: '压缩反馈',
  sleep: '休息中',
  alert: '上下文告警',
  empty: '状态未知',
};

function SpriteCrop({crop}: {crop: Crop}) {
  return (
    <svg
      viewBox={`0 0 ${crop.width} ${crop.height}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden
    >
      <image
        href={SHEET_SRC}
        x={-crop.x}
        y={-crop.y}
        width={SHEET_WIDTH}
        height={SHEET_HEIGHT}
        preserveAspectRatio="none"
      />
    </svg>
  );
}

export function IslandCompanion({
  visibility,
  mode,
  reducedMotion = false,
  location = 'island',
}: {
  visibility: IslandCompanionVisibility;
  mode: IslandCompanionMode;
  reducedMotion?: boolean;
  location?: CharacterLocation;
}) {
  if (visibility === 'hidden') return null;
  const emotion = EMOTION_SRC[mode];
  const showHeadOnly = visibility === 'head';
  const style = reducedMotion ? {transitionDelay: '0s'} : undefined;
  return (
    <div
      className={`xy-context-island__companion ${showHeadOnly ? 'is-head' : ''} is-visible`}
      data-companion-mode={mode}
      data-location={location}
      aria-label={`上下文小岛角色：${MODE_LABEL[mode]}`}
      style={style}
    >
      <div className="xy-context-island__sprite-window">
        <SpriteCrop crop={CROPS[mode]} />
      </div>
      {emotion ? (
        <img
          className="xy-context-island__emotion is-visible"
          src={emotion}
          alt=""
          aria-hidden
          style={style}
        />
      ) : null}
    </div>
  );
}
