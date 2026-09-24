/**
 * CLI 参数解析（从 index.tsx 抽出来的纯函数，便于直接用用例喂）。
 *
 * 抽出来的理由是两个实测缺陷都源自"带值选项的清单被抄了两遍且已经不一致"：
 * - ``argValue`` 把紧跟其后的**另一个选项**当成取值 —— ``--cwd --json hi``
 *   会拿 ``"--json"`` 当工作区目录，同时 JSON 模式悄悄失效（用户既进不了
 *   机器可读模式，又把一个不存在的目录当成了工程）。
 * - ``positionalPrompt`` 的跳过清单里**没有** ``--format`` —— 于是
 *   ``xeyo --format json "hi"`` 的自由文本提示词变成 ``"json hi"``。
 * 两处现在共用 ``VALUE_OPTIONS`` 一份清单。
 */

/** 需要跟一个值的选项。新增带值选项时必须改这里（两处解析都读这一份）。 */
export const VALUE_OPTIONS: readonly string[] = [
  "--cwd",
  "--session",
  "--provider",
  "--model",
  "-m",
  "--api-key",
  "--base-url",
  "--permission-mode",
  "--agent-mode",
  "--color",
  "--format",
];

/** 看起来像选项（而不是取值）的 token。单个 "-" 不算。 */
export function isOptionLike(token: string): boolean {
  return typeof token === "string" && token.length > 1 && token.startsWith("-");
}

/**
 * 取 ``--name value`` 或 ``--name=value`` 的值。
 *
 * ``=`` 形式优先，且空串也算用户显式给的值；空格形式**绝不**把下一个选项吞成值
 * —— 那会让后面的选项整体失效。
 */
export function argValue(argv: string[], name: string): string | undefined {
  const pref = `${name}=`;
  const inline = argv.find((a) => a.startsWith(pref));
  if (inline !== undefined) return inline.slice(pref.length);
  const i = argv.indexOf(name);
  if (i < 0) return undefined;
  const next = argv[i + 1];
  if (next === undefined || isOptionLike(next)) return undefined;
  return next;
}

/** 写了带值选项却没给值的那些选项名，供入口报错退出而不是静默走默认值。 */
export function missingOptionValues(argv: string[]): string[] {
  const bad: string[] = [];
  for (const name of VALUE_OPTIONS) {
    const i = argv.indexOf(name);
    if (i < 0) continue; // `--name=value` 是另一个 token，不会走到这里
    const next = argv[i + 1];
    if (next === undefined || isOptionLike(next)) bad.push(name);
  }
  return bad;
}

/** 收集末尾的自由文本提示词（位于各 flag 之后）。 */
export function positionalPrompt(argv: string[]): string {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--") {
      out.push(...argv.slice(i + 1));
      break;
    }
    if (isOptionLike(a)) {
      // 只跳过"本选项 + 它的取值"；取值本身不能是另一个选项（与 argValue 同判据），
      // 否则 `--format json` 这种没登记的串会把 `json` 漏成提示词。
      const takes =
        VALUE_OPTIONS.includes(a) ||
        VALUE_OPTIONS.some((n) => a.startsWith(`${n}=`));
      if (takes && !a.includes("=")) {
        const next = argv[i + 1];
        if (next !== undefined && !isOptionLike(next)) i += 1;
      }
      continue;
    }
    out.push(a);
  }
  return out.join(" ").trim();
}
