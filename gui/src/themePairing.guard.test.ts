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

/**
 * CSS 层：字面色只允许出现在三种地方（本轮把 styles/*.css 的 119 处逐个分过类）：
 * 1. 自定义属性**定义**里 —— 分类调色板（`--map-band: #5b8def`）与明暗成对色都住这里，
 *    本规则只看 `color:` / `background*:` / `fill:` / `stroke:`，不碰 `--*:`；
 * 2. 渐变/遮罩的色标里 —— `mask-image: linear-gradient(90deg, transparent, #000 14%)`
 *    用的是亮度通道，不是颜色；
 * 3. 主题作用域内 —— `html[data-scheme="dark"] .xy-user-prompt{color:#fff}`
 *    本身就是"深色这一档"的取值。
 * 除这三种以外写死字面色就是异色岛（不跟主题翻）。
 */
type CssDecl = {decl: string; stack: string[]; line: number};

function cssDecls(src: string): CssDecl[] {
  const out: CssDecl[] = [];
  const stack: string[] = [];
  let buf = '';
  let line = 1;
  for (const ch of src) {
    if (ch === '\n') line++;
    if (ch === '{') {
      stack.push(buf.replace(/\s+/g, ' ').trim());
      buf = '';
      continue;
    }
    if (ch === '}') {
      stack.pop();
      buf = '';
      continue;
    }
    if (ch === ';') {
      if (stack.length) out.push({decl: buf.replace(/\s+/g, ' ').trim(), stack: [...stack], line});
      buf = '';
      continue;
    }
    buf += ch;
  }
  return out;
}

describe('CSS 层不出现未分主题的写死色', () => {
  const cssDir = resolve(process.cwd(), 'src/styles');
  const files = readdirSync(cssDir).filter(f => f.endsWith('.css'));
  const all = files.flatMap(f =>
    cssDecls(
      readFileSync(resolve(cssDir, f), 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''),
    ).map(d => ({...d, file: f})),
  );

  const COLOR_PROPS = /^(color|background|background-color|fill|stroke)\s*:\s*(.+)$/;
  const themeScoped = (stack: string[]) =>
    stack.some(s => /\[data-scheme|\[data-theme|prefers-color-scheme/.test(s));

  // 每个文件里"在主题作用域下出现过"的类名 —— 用来识别"浅色为默认 + 深色另开一块"
  // 的成对写法。这类字面色不是岛：它有另一档陪着。
  const themedClassesByFile = new Map<string, Set<string>>();
  for (const f of files) {
    const set = new Set<string>();
    for (const d of all.filter(x => x.file === f)) {
      if (!themeScoped(d.stack)) continue;
      for (const s of d.stack) {
        for (const m of s.matchAll(/\.[a-zA-Z][\w-]+/g)) set.add(m[0]);
      }
    }
    themedClassesByFile.set(f, set);
  };

  const violations = all
    .map(d => {
      const m = COLOR_PROPS.exec(d.decl);
      if (!m) return null;
      const value = m[2];
      if (/gradient\(|url\(/.test(value)) return null;
      if (themeScoped(d.stack)) return null;
      // 有意豁免：低 alpha 的**背景底纹**（≤25%）。它按定义是与底下任何东西混合，
      // 不会造成"读不出"，也不需要跟主题翻 —— 例：diff 的 hunk 头
      // `background: rgb(56 139 253 / 0.1)`。前景色（color/fill/stroke）不在此列。
      if (m[1] === 'background' || m[1] === 'background-color') {
        const alpha =
          /\/\s*([\d.]+)\s*\)/.exec(value) ?? /,\s*([\d.]+)\s*\)/.exec(value);
        if (alpha && Number(alpha[1]) <= 0.25) return null;
      }
      const literals = value.replace(/var\([^()]*\)/g, 'V');
      if (!/#[0-9a-fA-F]{3,8}\b|\brgba?\(/.test(literals)) return null;
      // 选择器里任一 class 在本文件有主题作用域的对应块 ⇒ 成对写法，放过
      const sel = d.stack.at(-1) ?? '';
      const classes = [...sel.matchAll(/\.[a-zA-Z][\w-]+/g)].map(x => x[0]);
      const themed = themedClassesByFile.get(d.file) ?? new Set<string>();
      if (classes.some(c => themed.has(c))) return null;
      return d;
    })
    .filter((d): d is CssDecl & {file: string} => !!d);

  it('解析到了足够多的声明（防止解析空跑让断言假绿）', () => {
    expect(all.length).toBeGreaterThan(1500);
    expect(files.length).toBeGreaterThan(10);
  });

  it('成对判据本身有效（浅色默认+深色另开块的选择器确实被识别）', () => {
    // 没有这条，"对应块"识别失效时上一条会退化成全放过或全误报。
    const prism = all.find(
      x => x.file === 'app-chrome-shell.css' && /\.xy-prism-html \.token\.keyword/.test(x.stack.at(-1) ?? ''),
    );
    expect(prism).toBeDefined();
    expect(themedClassesByFile.get('app-chrome-shell.css')?.has('.xy-prism-html')).toBe(true);
  });

  it('写死色只出现在调色板定义 / 渐变色标 / 主题作用域三处', () => {
    expect(
      violations.map(v => `${v.file}:${v.line}  ${v.stack.at(-1)?.slice(0, 44)}  {${v.decl.slice(0, 52)}}`),
    ).toEqual([]);
  });
});
