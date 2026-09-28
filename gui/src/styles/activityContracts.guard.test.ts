/// <reference types="node" />
/**
 * activity.css（agent 工作过程的可读性层）的可执行契约。
 *
 * 全部断言来自 2026-09-27 r4 的实测（?scenario=lifecycle：settled 19 步 / live 20 /
 * stopped 14，paper+basalt × 1680+900 × 正常/系统减弱动效/平滑开关，像素级采样）。
 * 每条都对应一个量出来的失败，不是审美条款：
 *
 * C1 轨内文字一律不许用带 alpha 的前景（旧 data-headless 规则把 mute 稀释到 88%，
 *    paper 上实测 3.91:1 < 4.5，且同特异度压掉了第 5 节的错误前景）。
 * C2 三个只读族 read / search / todo 必须各有自己的族钩子与不同计算量
 *    （旧版五族同签：[todo≈read≈search≈sub-agent]）。
 * C3 子 Agent 派工行必须靠 data-xy-agent 上色，不许只靠 :has(+ .xy-agent-done-list)
 *    （落定态卡片不在轨内，实测命中 0 行）。
 * C4 失败行必须在「同时是命令」时仍保住 danger：需要并写的 :has(.is-cmd) /
 *    [data-xy-cat="run"] 变体，否则 3.1 的 (0,5,0) 命令档把错误前景与 ✕ 吃掉。
 * C5 动词（.xy-morph）的颜色归产品自己（is-ok / is-error / thought 三档），
 *    本层只准改字号。
 * C6 长输出必须有硬顶 + 内部滚动（实测 clientHeight 260 < scrollHeight 788/1448/2091）。
 * C7 每一条 infinite 动画都必须同时被 html[data-smoothness="off"] 门控
 *    （实测 .xy-thinking 的 shimmer 只被 prefers-reduced-motion 那条路挡掉，
 *    应用内「关平滑」时轨外仍留 1 个无限动画）。
 * C8 折叠聚合视图（.xy-workflow-fold）只准收留白，不许上字号/颜色/底色，
 *    否则第 2/3/5 节在用户唯一看得到的落定态里全部作废。
 * C9 中文槽位不许字距；只有 Args / Output 两个拉丁常量标签例外。
 * C10 markup 侧的两个表现层钩子必须还在（data-xy-cat / data-xy-agent），
 *    且 isCommand 谓词必须仍带 cat 分支——这是失败命令不再掉 .is-cmd 的唯一保证。
 *
 * 读文件一律走 node:fs：`import css from '*.css?raw'` 会被 Vite 的 CSS 插件折进样式管线，
 * 测试里拿到的是空串，所有断言会静默空跑（因此每条都带解析量前置断言）。
 */
import {readFileSync, existsSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {describe, expect, it} from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '../..');
const CSS_PATH = resolve(HERE, 'activity.css');

const stripComments = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '');
const normalize = (s: string) => s.replace(/\s+/g, ' ').trim();
const css = stripComments(readFileSync(CSS_PATH, 'utf8'));

type Rule = {selector: string; body: string; at: string[]};

/** 只剥注释、不认嵌套规则：本层 css 没有 style-rule 内嵌套（at-rule 除外）。 */
function parseRules(src: string): Rule[] {
  const out: Rule[] = [];
  const walk = (text: string, at: string[]) => {
    for (let i = 0; i < text.length; ) {
      const open = text.indexOf('{', i);
      if (open < 0) break;
      const selector = normalize(text.slice(i, open));
      let depth = 1;
      let close = open + 1;
      while (close < text.length && depth > 0) {
        const ch = text[close];
        if (ch === '{') depth += 1;
        else if (ch === '}') depth -= 1;
        close += 1;
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

const rules = parseRules(css);
/** 规则里的声明（按 ; 切；color-mix 里没有分号，够用）。 */
const declsOf = (r: Rule) =>
  r.body
    .split(';')
    .map(d => normalize(d))
    .filter(Boolean);
const decls = rules.flatMap(declsOf);
const rulesWith = (re: RegExp) => rules.filter(r => re.test(r.selector));
const rulesDecl = (selRe: RegExp, declRe: RegExp) =>
  rulesWith(selRe).filter(r => declsOf(r).some(d => declRe.test(d)));

/** 顶层逗号组：括号 / 方括号内的逗号不算分隔。 */
function splitSelectorGroup(sel: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = '';
  for (const ch of sel) {
    if (ch === '(' || ch === '[') depth += 1;
    else if (ch === ')' || ch === ']') depth -= 1;
    if (ch === ',' && depth === 0) {
      out.push(normalize(cur));
      cur = '';
    } else cur += ch;
  }
  if (normalize(cur)) out.push(normalize(cur));
  return out.filter(Boolean);
}

describe('activity.css 契约（agent 工作过程展示）', () => {
  it('解析面不为空（防止读错路径让断言空跑）', () => {
    expect(existsSync(CSS_PATH)).toBe(true);
    expect(rules.length).toBeGreaterThan(60);
    expect(decls.length).toBeGreaterThan(120);
  });

  it('C1 轨内文字前景不带 alpha：color: …, transparent) 一律禁止', () => {
    const textSelectors =
      /\.xy-split-(preview|result|right|left)|\.xy-morph|\.xy-split-bullet|\.xy-chat-text|(^|,)pre\b/;
    const alphaText = rules
      .filter(r => splitSelectorGroup(r.selector).some(s => textSelectors.test(s)))
      .flatMap(r =>
        declsOf(r)
          .filter(d => /^color:/.test(d) && /,\s*transparent\s*\)/.test(d))
          .map(d => `${r.selector} { ${d} }`),
      );
    expect(alphaText).toEqual([]);
  });

  it('C1b 不写死字面色（只允许 var(--xy-*) / color-mix / 关键字）', () => {
    const literals = decls.filter(d =>
      /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|lab|lch|oklch|oklab|color)\(/.test(d),
    );
    expect(literals).toEqual([]);
  });

  it('C2 read / search / todo 三族各有钩子，且计算量两两不同', () => {
    const read = rulesDecl(/\[data-xy-cat="read"\]/, /font-size:/);
    const search = rulesDecl(/\[data-xy-cat="search"\]/, /font-size:/);
    const todo = rulesDecl(/\[data-xy-cat="todo"\]/, /(font-size|color):/);
    expect(read.length).toBeGreaterThan(0);
    expect(search.length).toBeGreaterThan(0);
    expect(todo.length).toBeGreaterThan(0);
    const size = (rs: Rule[]) => rs.flatMap(declsOf).find(d => /^font-size:/.test(d)) || '';
    // 读比搜小一档；计划族靠前景（ink-soft）而不是靠 alpha 与搜分开。
    expect(size(read)).toMatch(/--xy-act-read/);
    expect(size(search)).toMatch(/--xy-act-quiet/);
    expect(declsOf(todo[0]!).join(';')).toMatch(/--xy-ink-soft/);
    // 尺子上 read 必须严格小于 quiet（安静档永远不比改动/命令响）。
    const ruler = css.match(/\.xy-activity-split\s*\{[\s\S]*?\}/);
    expect(ruler).not.toBeNull();
    const readPx = Number(/--xy-act-read:\s*([\d.]+)px/.exec(ruler![0])?.[1]);
    const quietPx = Number(/--xy-act-quiet:\s*([\d.]+)px/.exec(ruler![0])?.[1]);
    const bodyPx = Number(/--xy-act-body:\s*([\d.]+)px/.exec(ruler![0])?.[1]);
    expect(readPx).toBeGreaterThan(0);
    expect(readPx).toBeLessThan(quietPx);
    expect(quietPx).toBeLessThan(bodyPx);
  });

  it('C3 子 Agent 派工行用 data-xy-agent，不靠卡片邻接', () => {
    const agentRules = rulesWith(/\[data-xy-agent="1"\]/);
    expect(agentRules.length).toBeGreaterThan(1);
    const sans = agentRules.flatMap(declsOf).filter(d => /font-family:\s*var\(--font-sans\)/.test(d));
    expect(sans.length).toBeGreaterThan(0);
    // 邻接选择器只许留在「卡片条留白」那一条上，不再承担上色。
    const adjacencyStyled = rulesWith(/:has\(\+\s*\.xy-agent-done-list\)/).filter(r =>
      declsOf(r).some(d => /^(color|font-family|font-size):/.test(d)),
    );
    expect(adjacencyStyled.map(r => r.selector)).toEqual([]);
  });

  it('C4 失败行在「同时是命令 / 派工」时仍保住 danger（并写变体存在）', () => {
    for (const target of [
      '.xy-split-preview',
      '.xy-split-bullet',
      '.xy-morph',
    ] as const) {
      const plain = rulesDecl(new RegExp(`\\.is-failed .*\\${target}$`), /color:/);
      const cmd = rulesDecl(
        new RegExp(`\\.is-failed(?::has\\(\\.xy-split-preview\\.is-cmd\\)|\\[data-xy-(cat|agent)=)`),
        /color:/,
      );
      expect(plain.length, target).toBeGreaterThan(0);
      expect(cmd.length, target).toBeGreaterThan(0);
    }
  });

  it('C5 动词颜色归产品：第 2 节那条 blanket .xy-morph 规则只准留字号', () => {
    // 产品自己已有三档动词色（.xy-morph.is-error / .xy-split-step.is-ok .xy-morph /
    // .thought-step .xy-morph，全是 (0,3,0)）；本层任何同特异度的 blanket 颜色都会
    // 因为引入更晚把它们全部抹平（r4 实测：thought / edit 的动词与安静行逐字节同色）。
    const blanket = /^\.xy-activity-split \.xy-split-step \.xy-morph$/;
    const hit = rules.filter(r => splitSelectorGroup(r.selector).some(s => blanket.test(s)));
    expect(hit.length).toBe(1);
    const flat = declsOf(hit[0]!).join(';');
    expect(flat).toMatch(/font-size:/);
    expect(flat).not.toMatch(/(^|;)\s*color:/);
    // 族档（命令 / 派工 / 失败）自己上 morph 色是允许的，这里只挡 blanket。
    expect(rulesWith(/\[data-xy-agent="1"\] \.xy-morph|\.is-cmd\) \.xy-morph|\.is-failed .*\.xy-morph/).length).toBeGreaterThan(0);
  });

  it('C6 展开体有硬顶 + 内部滚动', () => {
    for (const sel of [
      /\.xy-tool-step-body\s+pre$/,
      /\.xy-diff-preview$/,
      /\.xy-thought-expand-body$/,
    ]) {
      const hit = rules.filter(r =>
        splitSelectorGroup(r.selector).some(s => sel.test(s)),
      );
      expect(hit.length, String(sel)).toBeGreaterThan(0);
      const flat = hit.flatMap(declsOf).join(';');
      expect(flat, String(sel)).toMatch(/max-height:\s*var\(--xy-act-cap\)/);
      expect(flat, String(sel)).toMatch(/overflow:\s*auto|overflow-y:\s*auto/);
    }
    const cap = /--xy-act-cap:\s*(\d+)px/.exec(css);
    expect(Number(cap?.[1])).toBeGreaterThan(100);
  });

  it('C7 每条 infinite 动画都被 html[data-smoothness="off"] 门控', () => {
    const tail = (s: string) =>
      s
        .replace(/html\[data-smoothness="off"\]\s*/g, '')
        .replace(/\.xy-activity-split\s*/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    const animated = rules
      .filter(r => declsOf(r).some(d => /^animation:/.test(d) && /infinite/.test(d)))
      .flatMap(r => splitSelectorGroup(r.selector));
    expect(animated.length).toBeGreaterThan(0);
    const gated = rules
      .filter(r => /html\[data-smoothness="off"\]/.test(r.selector))
      .flatMap(r => splitSelectorGroup(r.selector).map(tail));
    const ungated = animated
      .map(tail)
      .filter(s => !gated.some(g => g.replace(/!important/, '') === s));
    expect(ungated).toEqual([]);
  });

  it('C7b 减弱动效的两条路都写全（媒体查询块存在且覆盖 pulse）', () => {
    const media = rules.filter(r => r.at.some(a => /prefers-reduced-motion/.test(a)));
    expect(media.length).toBeGreaterThan(1);
    expect(media.flatMap(r => splitSelectorGroup(r.selector)).join(',')).toMatch(
      /\.xy-split-pulse/,
    );
  });

  it('C8 聚合折叠视图只收留白，不上字号/颜色/底色', () => {
    const foldRules = rulesWith(/\.xy-workflow-fold/);
    expect(foldRules.length).toBeGreaterThan(0);
    const bad = foldRules.flatMap(r =>
      declsOf(r)
        .filter(d => /^(font-size|color|background(-color)?|border)\s*:/.test(d))
        .map(d => `${r.selector} { ${d} }`),
    );
    expect(bad).toEqual([]);
    // 折叠态只许通过尺子变量把留白收掉（第 10 节的那组 --xy-act-pad-*）。
    expect(foldRules.flatMap(declsOf).join(';')).toMatch(/--xy-act-pad-quiet:\s*0px/);
  });

  it('C9 中文槽位零字距；只有 Args / Output 标签允许字距', () => {
    const tracked = rules
      .filter(r => !/h4/.test(r.selector))
      .flatMap(r =>
        declsOf(r)
          .filter(d => /^letter-spacing:/.test(d) && !/normal|0px/.test(d))
          .map(d => `${r.selector} { ${d} }`),
      );
    expect(tracked).toEqual([]);
    const labels = rulesDecl(/\.xy-tool-step-body\s+h4$/, /letter-spacing:/);
    expect(labels.length).toBe(1);
  });

  it('C10 markup 侧的两个表现层钩子与 is-cmd 谓词仍在位', () => {
    const log = readFileSync(resolve(ROOT, 'src/components/ActivityLog.tsx'), 'utf8');
    const steps = readFileSync(resolve(ROOT, 'src/lib/toolActivity/steps.ts'), 'utf8');
    const types = readFileSync(resolve(ROOT, 'src/lib/toolActivity.ts'), 'utf8');
    expect(log).toMatch(/data-xy-cat=\{step\.cat\}/);
    expect(log).toMatch(/data-xy-agent=\{step\.agent \? '1'/);
    // 失败命令不许再掉回「失败的读」：谓词必须带 cat 分支。
    expect(log).toMatch(/step\.cat === 'run'/);
    // 两个 .ts 在工作树里是 CRLF（HEAD 存的是 LF），断言不能依赖行尾风格。
    expect(steps).toMatch(/^\s*cat,\s*$/m);
    expect(types).toMatch(/cat\?:\s*ToolCat/);
  });
});
