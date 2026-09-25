/**
 * 主题配对手艺的静态守卫（扫源码，不依赖浏览器）。
 *
 * 两条规则都来自实测到的真缺陷：
 * 1. `bg-warn` + `text-white`：浅色 2.53 / 深色 1.64，正文门槛 4.5——
 *    而它出现在「从检查点恢复」这种恢复流程主操作上。warn 在两套主题都是亮琥珀，
 *    前景必须走 `text-warn-ink`（实测 5.03 / 7.74）。
 * 2. `bg-black/[0.0x]` 当**表面**用（低 alpha 的浅色主题压暗色）：深色主题下
 *    对底噪比 1.01，等于看不见（消息流加载骨架就是这样）。整屏遮罩
 *    （bg-black/35|45）是有意的 scrim，不在此列。
 */
import {readdirSync, readFileSync, statSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, expect, it} from 'vitest';

const roots = ['src/components', 'src/features', 'src/pages'];

const sources = roots.flatMap(root => {
  const abs = resolve(process.cwd(), root);
  const walk = (dir: string): string[] => {
    const out: string[] = [];
    for (const name of readdirSync(dir)) {
      const p = resolve(dir, name);
      if (statSync(p).isDirectory()) out.push(...walk(p));
      else if (/\.tsx$/.test(name) && !/\.test\./.test(name)) out.push(p);
    }
    return out;
  };
  try {
    return walk(abs);
  } catch {
    return [];
  }
});

/** 剥掉注释，避免文档里写的「原先是 bg-black/[0.06]」被当成违规。 */
const stripComments = (src: string) =>
  src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter(l => !/^\s*(\/\/|\*)/.test(l))
    .join('\n');

const linesWith = (re: RegExp) =>
  sources.flatMap(f =>
    stripComments(readFileSync(f, 'utf8'))
      .split('\n')
      .map((l, i) => ({f: f.replace(process.cwd() + '/', ''), i: i + 1, l}))
      .filter(x => re.test(x.l)),
  );

describe('主题配对守卫', () => {
  it('扫描面不为空（防止路径写错让断言空跑）', () => {
    expect(sources.length).toBeGreaterThan(80);
  });

  it('亮色状态底上不放白字（warn/danger/ok + text-white）', () => {
    const hits = linesWith(/\bbg-(warn|danger|ok)\b/).filter(x =>
      /\btext-white\b/.test(x.l),
    );
    expect(hits.map(x => `${x.f}:${x.i}`)).toEqual([]);
  });

  it('低 alpha 的 bg-black 不当表面用（深色下不可见；整屏 scrim 除外）', () => {
    const hits = linesWith(/bg-black\/\[?0?\.0\d/);
    expect(hits.map(x => `${x.f}:${x.i} ${x.l.trim().slice(0, 60)}`)).toEqual([]);
  });

  it('warn 实心底上的文字必须走 text-warn-ink（/alpha 底纹不在此列）', () => {
    // bg-warn/10 + text-warn 是"底纹 + 同色文字"的正确配对；只有实心 bg-warn
    // 才需要深墨前景。所以这里排除带 alpha 的写法。
    const warnButtons = linesWith(/\bbg-warn\b(?!\/)/).filter(x => /text-/.test(x.l));
    for (const x of warnButtons) {
      expect(x.l).toMatch(/text-warn-ink/);
    }
    expect(warnButtons.length).toBeGreaterThanOrEqual(1);
  });
});
