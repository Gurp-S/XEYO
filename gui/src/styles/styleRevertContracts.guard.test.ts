/// <reference types="node" />
/**
 * 视觉层回退（→ 59f606f / 09-17）之后三处洞的可执行契约。
 *
 * D1  `.xy-app-surface`（AppShell.tsx:171 在用）回退时被整块删掉，而 shell.css 的 `#root`
 *     还残留着一团 radial 色斑 → 基面一律要求扁平纸面，`#root` 不再画任何渐变。
 * D2  HEAD `base.css` 被删的 74 行里，有两块回退后没人补：小控件圆角归一化块
 *     （6/7/8px 散值收口）与 `.xy-caret` 的 prefers-reduced-motion 伴生块。
 * D3  `workbench.css` 曾有两条 `div[class*="hover:bg-glass"]` / `div[class~="rounded-full"]`
 *     式的宽匹配：前者会命中面板里任何挂着 hover 类的后代 div，后者会抹掉任何圆形 chip。
 *     这里把"行 = 列表项的直接子节点 + 完整 hover token"和"只抹欢迎块首子的图标井"
 *     写成断言，并核对该形状锚的类仍是活代码——注释里的 >-形状声明不再是口头承诺。
 *
 * 读文件一律走 node:fs：`import css from '*.css?raw'` 会被 Vite 的 CSS 插件折进样式管线，
 * 测试里拿到的是空串，所有断言会静默空跑（因此下面每条都带解析量前置断言）。
 */
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {describe, expect, it} from 'vitest';

const stylesDir = resolve(process.cwd(), 'src/styles');

/** 本契约约束的样式文件（entry.css 的引入顺序 = 层叠优先级）。 */
const CONTRACTED = [
  'base.css',
  'shell.css',
  'sidebar.css',
  'tokens.css',
  'revert-compat.css',
  'workbench.css',
];

const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '');
const normalize = (s: string) => s.replace(/\s+/g, ' ').trim();
const readStyle = (name: string) => readFileSync(resolve(stylesDir, name), 'utf8');
const readSrc = (...rel: string[]) =>
  readFileSync(resolve(process.cwd(), ...rel), 'utf8');

type Rule = {selector: string; body: string; at: string[]; file: string; order: number};

/** 只剥注释、不认嵌套规则：本层 css 没有 style-rule 内嵌套（at-rule 除外）。 */
function parseRules(src: string): {selector: string; body: string; at: string[]}[] {
  const out: {selector: string; body: string; at: string[]}[] = [];
  const walk = (text: string, at: string[]) => {
    for (let i = 0; i < text.length; ) {
      const open = text.indexOf('{', i);
      if (open < 0) break;
      const selector = normalize(text.slice(i, open));
      let depth = 1;
      let close = open + 1;
      while (close < text.length && depth > 0) {
        const ch = text[close];
        if (ch === '{') depth++;
        else if (ch === '}') depth--;
        close++;
      }
      const body = text.slice(open + 1, close - 1);
      if (/^@(media|container|supports|layer)\b/.test(selector)) {
        walk(body, [...at, selector]);
      } else if (!selector.startsWith('@')) {
        out.push({selector, body, at});
      }
      i = close;
    }
  };
  walk(src, []);
  return out;
}

/** 顶层逗号切分选择器组：括号 / 方括号 / 引号内的逗号不算分隔。 */
function selectorGroups(selector: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let buf = '';
  let quote: string | null = null;
  for (const ch of selector) {
    if (quote) {
      buf += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      buf += ch;
      continue;
    }
    if (ch === '(' || ch === '[') depth++;
    if (ch === ')' || ch === ']') depth--;
    if (ch === ',' && depth === 0) {
      if (buf.trim()) out.push(buf.trim());
      buf = '';
      continue;
    }
    buf += ch;
  }
  if (buf.trim()) out.push(buf.trim());
  return out;
}

/** 类名一律 [\w-]+：[a-z0-9-]+ 会在大写字母处截断类名，重命名就杀不掉断言。 */
const CLASS_RE = /\.([A-Za-z][\w-]*)/g;
const classesOf = (selector: string) =>
  [...selector.matchAll(CLASS_RE)].map(m => m[1]);

/** 结构锚点必须**紧邻**子代组合器 —— `X > node` 成立，`X node`（任意后代）不成立。 */
const childAnchored = (selector: string, anchor: string) =>
  new RegExp(`${anchor.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*>`).test(selector);

/** entry.css 的 @import 递归展开顺序（barrel 子文件排在 barrel 之后、下一个兄弟之前）。 */
function importSequence(): Map<string, number> {
  const order = new Map<string, number>();
  let n = 0;
  const visit = (abs: string) => {
    if (order.has(abs)) return;
    order.set(abs, n++);
    let src = '';
    try {
      src = readFileSync(abs, 'utf8');
    } catch {
      return;
    }
    for (const m of src.matchAll(/@import\s+["']([^"']+)["']/g)) {
      const spec = m[1];
      if (!spec.endsWith('.css')) continue;
      visit(resolve(dirname(abs), spec));
    }
  };
  visit(resolve(stylesDir, 'entry.css'));
  return order;
}

const seq = importSequence();
const posOf = (file: string) => seq.get(resolve(stylesDir, file)) ?? -1;

const rulesByFile = new Map<string, Rule[]>();
for (const file of CONTRACTED) {
  const src = readStyle(file);
  const base = posOf(file);
  rulesByFile.set(
    file,
    parseRules(stripComments(src)).map((r, i) => ({...r, file, order: base * 1000 + i})),
  );
}
const allRules = [...rulesByFile.values()].flat();
const rulesIn = (file: string) => rulesByFile.get(file) ?? [];
const byOrder = (rules: Rule[]) => [...rules].sort((a, b) => a.order - b.order);

/** tsx 里出现过的 class token（活代码判据）：整目录扫，避免逐个文件拼路径拼错。 */
const tokensOf = (src: string) => new Set([...src.matchAll(/[\w-]+/g)].map(m => m[0]));
const tsxTokens = (roots: string[]) => {
  const tokens = new Set<string>();
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = resolve(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.tsx$/.test(name)) for (const t of tokensOf(readFileSync(p, 'utf8'))) tokens.add(t);
    }
  };
  for (const root of roots) {
    try {
      walk(resolve(process.cwd(), root));
    } catch {
      /* 目录不存在：由下面的 aggregate 断言负责暴露 */
    }
  }
  return tokens;
};

const liveTokens = tsxTokens(['src/components', 'src/pages', 'src/features', 'src/ui']);

describe('CSS 回退契约 · 解析前置', () => {
  it('每条契约都真的读到了内容（空串会让全部断言静默假绿）', () => {
    for (const file of CONTRACTED) expect(readStyle(file).length).toBeGreaterThan(300);
    expect(allRules.length).toBeGreaterThan(60);
    expect(liveTokens.size).toBeGreaterThan(500);
    /* 三块出洞的文件各自必须有像样的解析量 */
    for (const file of ['shell.css', 'revert-compat.css', 'workbench.css']) {
      expect(rulesIn(file).length, file).toBeGreaterThan(20);
    }
  });

  it('entry.css 的引入顺序解析成功（层叠判据依赖它）', () => {
    expect(seq.size).toBeGreaterThan(15);
    expect(posOf('revert-compat.css')).toBeGreaterThan(posOf('base.css'));
  });
});

describe('D1 · 应用基面 .xy-app-surface 扁平，#root 不残留色斑', () => {
  const surface = rulesIn('shell.css').filter(r =>
    selectorGroups(r.selector).includes('.xy-app-surface'),
  );

  it('组件在用的 .xy-app-surface 有且只有一处定义', () => {
    expect(tokensOf(readSrc('src', 'components', 'AppShell.tsx')).has('xy-app-surface')).toBe(
      true,
    );
    expect(surface.map(r => r.selector)).toEqual(['.xy-app-surface']);
  });

  it('基面是 var(--xy-paper) 的扁平纸面：无渐变、无阴影', () => {
    const body = surface[0]?.body ?? '';
    expect(body).toMatch(/background(-color)?:\s*var\(--xy-paper\)/);
    expect(body).not.toMatch(/gradient\(/);
    expect(body).not.toMatch(/box-shadow/);
  });

  it('任何 #root 规则都不再画渐变（含未被本轮改动的 chat.css）', () => {
    const extra = parseRules(stripComments(readStyle('chat.css'))).map(r => ({
      ...r,
      file: 'chat.css',
      order: posOf('chat.css') * 1000,
    }));
    const rootRules = [...allRules, ...extra].filter(r =>
      selectorGroups(r.selector).some(s => /(^|[\s>+~])#root($|[^\w-])/.test(s)),
    );
    expect(rootRules.length).toBeGreaterThan(3);
    for (const r of rootRules) {
      /* 断整条 body，不截断：截到 80 字符会把 background 后面的渐变证据切掉。 */
      expect(r.body, `${r.file} ${r.selector}`).not.toMatch(/gradient\(/);
    }
  });

  it('shell.css 整个文件不画 radial 色斑（基面一律扁平，不是只改一条规则）', () => {
    expect(stripComments(readStyle('shell.css'))).not.toMatch(/radial-gradient\(/);
  });
});

describe('D2 · HEAD base.css 被删而没人补的两块', () => {
  const NORMALISED = [
    'xy-icon-btn',
    'xy-pressable',
    'xy-menu-row',
    'xy-palette-filter',
    'xy-turn-rail-row',
    'xy-ctx-row',
  ];

  const normaliser = allRules.filter(
    r =>
      /border-radius:\s*var\(--xy-radius-tight\)/.test(r.body) &&
      // 每个组允许挂 :not(...) 豁免尾巴（见下条用例），比对时剥掉再认类名。
      NORMALISED.every(c =>
        selectorGroups(r.selector).some(sel => sel.replace(/:not\([^)]*\)/g, '').trim() === `.${c}`),
      ),
  );

  it('小控件圆角归一化块在位，六个类一处收口', () => {
    expect(normaliser.map(r => `${r.file} ${r.selector}`)).toHaveLength(1);
  });

  it('六个类一律豁免显式 rounded-full —— 无层规则会压过 @layer utilities，不豁免就把圆钮切成方角', () => {
    expect(normaliser).toHaveLength(1);
    const groups = selectorGroups(normaliser[0]!.selector);
    expect(groups).toHaveLength(NORMALISED.length);
    for (const g of groups) {
      expect(g, g).toMatch(/^\.xy-[\w-]+:not\(\[class~="rounded-full"\]\)$/);
    }
  });

  it('收口只收到 tight 一档，不蹭 control / float / pane', () => {
    expect(normaliser[0]?.body ?? '').not.toMatch(/var\(--xy-radius-(control|float|pane)\)/);
  });

  it('六个类都还被活代码使用（归一化块不是对着死类写的）', () => {
    for (const cls of NORMALISED) expect(liveTokens.has(cls), cls).toBe(true);
  });

  it('caret 的 prefers-reduced-motion 伴生块在位', () => {
    const reduced = allRules.filter(
      r =>
        selectorGroups(r.selector).includes('.xy-caret') &&
        r.at.some(a => /prefers-reduced-motion/.test(a)),
    );
    expect(reduced.map(r => `${r.file} ${r.selector}`)).toHaveLength(1);
    expect(reduced[0]?.body ?? '').toMatch(/transition:\s*none/);
    /* 只撤补间，不撤 180° 朝向：朝向是开合状态的载体。 */
    expect(reduced[0]?.body ?? '').not.toMatch(/transform/);
  });

  it('reduced-motion 块在层叠上晚于 caret 的 transition（同特异度靠源序）', () => {
    const tween = allRules.filter(
      r => selectorGroups(r.selector).includes('.xy-caret') && /transition:/.test(r.body) && !r.at.length,
    );
    const reduced = allRules.filter(
      r => selectorGroups(r.selector).includes('.xy-caret') && /transition:\s*none/.test(r.body),
    );
    expect(tween.length).toBeGreaterThan(0);
    expect(reduced.length).toBeGreaterThan(0);
    expect(byOrder(reduced)[0].order).toBeGreaterThan(byOrder(tween)[0].order);
  });

  it('归一化块晚于 app-turn-rail.css（那里残留 7px 散值，同特异度必须靠后）', () => {
    expect(posOf('app-turn-rail.css')).toBeGreaterThan(0);
    expect(posOf(normaliser[0]?.file ?? '')).toBeGreaterThan(posOf('app-turn-rail.css'));
  });
});

describe('D3 · workbench.css 的两条宽匹配已换成形状判据', () => {
  const wb = rulesIn('workbench.css');

  it('行规格 / 抹除类规则的选择器里不得有 [class*=] 子串匹配', () => {
    const offenders = wb
      .filter(r => /border-radius:\s*0|padding-block|display:\s*none/.test(r.body))
      .filter(r => /\[class\*=/.test(r.selector))
      .map(r => r.selector);
    expect(offenders).toEqual([]);
  });

  it('整文件不得出现 div[class*=…]（任何后代 div 挂着该子串都算命中）', () => {
    expect(stripComments(readStyle('workbench.css'))).not.toMatch(/\bdiv\[class\*=/);
  });

  it('面板行必须挂在列表项的直接子节点上，且带完整 hover token', () => {
    const rowRules = wb.filter(
      r => /border-radius:\s*0/.test(r.body) && /padding-block:\s*3px/.test(r.body),
    );
    expect(rowRules.length).toBeGreaterThanOrEqual(3); // 树行 + 历史/提交行 + git 状态行
    for (const r of rowRules) {
      expect(r.selector, r.selector).toMatch(/\s>\s/);
      expect(classesOf(r.selector).length).toBeGreaterThan(0);
    }
    const panelRow = rowRules.find(r => /\[class~="hover:bg-glass-hover"\]/.test(r.selector));
    expect(panelRow?.selector ?? '').toMatch(/class~="group"/);
    /* 锚点必须**紧邻**子代组合器：`[class~="group"] div[…]`（退成后代）不算收紧。 */
    expect(childAnchored(panelRow?.selector ?? '', '[class~="group"]')).toBe(true);
    const statusRow = rowRules.find(r =>
      /\[class~="hover:bg-glass-hover\/50"\]/.test(r.selector),
    );
    expect(childAnchored(statusRow?.selector ?? '', '[class~="mb-2"]')).toBe(true);
    const treeRow = rowRules.find(r => /class~="bg-glass-strong"|xy-pressable/.test(r.selector));
    expect(childAnchored(treeRow?.selector ?? '', 'li')).toBe(true);
  });

  it('行内主按钮归零同样锁在 > 形状上', () => {
    const inner = wb.filter(
      r => /padding-block:\s*0/.test(r.body) && /line-height:\s*20px/.test(r.body),
    );
    expect(inner).toHaveLength(1);
    expect(inner[0].selector).toMatch(/>\s*button\[class~="py-1"\]/);
    expect(childAnchored(inner[0].selector, '[class~="group"]')).toBe(true);
  });

  it('display:none 只抹欢迎块首子的圆形图标井，不抹任意 rounded-full', () => {
    const kill = wb.filter(r => /display:\s*none/.test(r.body));
    expect(kill).toHaveLength(1);
    const sel = kill[0]?.selector ?? '';
    expect(sel).toMatch(/class~="max-w-sm"/);
    expect(sel).toMatch(/:not\(\[class~="w-full"\]\)/);
    expect(childAnchored(sel, ':not([class~="w-full"])')).toBe(true);
    expect(sel).toMatch(/\s>\s/);
    expect(sel).toMatch(/:first-child/);
    expect(sel).toMatch(/:has\(\s*>\s*svg\s*\)/);
    expect(sel).toMatch(/class~="h-10"/);
    expect(sel).toMatch(/class~="rounded-full"/);
  });

  it('这些形状锚点仍对应活代码（注释里的 >-形状声明在这里被核对）', () => {
    const literals = [
      ...readSrc('src', 'components', 'WorkspaceToolPanel.tsx').matchAll(/className="([^"]+)"/g),
    ].map(m => m[1]);
    /* 完整 token 判据：`py-1` 不得匹配到 `py-1.5`，`hover:bg-glass-hover` 不得匹配到
       `hover:bg-glass-hover/50`——否则"收紧"只是换了一种子串匹配。 */
    const withTokens = (...tokens: string[]) =>
      literals.filter(c =>
        tokens.every(t => {
          const esc = t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          return new RegExp(`(^|\\s)${esc}(\\s|$)`).test(c);
        }),
      );
    expect(withTokens('hover:bg-glass-hover', 'flex', 'items-center').length).toBe(2);
    expect(withTokens('hover:bg-glass-hover/50', 'flex', 'items-center').length).toBe(1);
    expect(literals).toContain('group');
    expect(withTokens('py-1', 'min-w-0', 'flex-1').length).toBe(2);

    const browser = readSrc('src', 'components', 'BrowserPreviewPanel.tsx');
    expect(browser).toMatch(
      /className="mx-auto flex max-w-sm flex-col items-center gap-2 text-center"/,
    );
    expect(browser).toMatch(
      /className="flex h-10 w-10 items-center justify-center rounded-full/,
    );
  });
});
