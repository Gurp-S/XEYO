/** 用于渲染器回归测试的极端 markdown 夹具。 */

export const MD_BASIC = `# Title
## Sub
Paragraph with **bold**, *italic*, ~~strike~~, and \`inline\`.

- list a
- list b

1. one
2. two

> quote line

---

[link](https://example.com)
`;

export const MD_TABLE = `| A | B |
| --- | --- |
| 1 | 2 |
| x | y |`;

export const MD_CODE_JS = `Before

\`\`\`javascript
function hello(name) {
  return \`hi \${name}\`;
}
\`\`\`

After`;

export const MD_CODE_EMPTY = `\`\`\`python

\`\`\``;

export const MD_CODE_UNKNOWN_LANG = `\`\`\`not-a-real-lang-xyz
foo bar
\`\`\``;

export const MD_CODE_ALIAS = `\`\`\`ts
const x: number = 1;
\`\`\``;

export const MD_INCOMPLETE_FENCE = `Intro

\`\`\`python
def foo():
    return 1
`;

export const MD_NESTED_BACKTICKS = `\`\`\`markdown
Use \`code\` and **bold** inside.
\`\`\``;

export const MD_TASKS = `- [x] done
- [ ] todo`;

export const MD_HTML_INJECTION = `Hello <script>alert(1)</script> world

<img src=x onerror=alert(1)>

[bad](javascript:alert(1))
[ok](https://example.com)
`;

export const MD_CONTROL_CHARS = `Line\u0000with\u0007nulls

\`\`\`js
a\u0000b
\`\`\``;

export const MD_CJK = `中文**加粗**与\`代码\`

\`\`\`python
print("你好")
\`\`\`

| 列 | 值 |
| --- | --- |
| 甲 | 乙 |`;

export const MD_HEADINGS = `# H1
## H2
### H3
#### H4
##### H5
###### H6`;

export const MD_MATH = `状态 $P_s$ 与

$$ S=(P_s, P_c, M, T_k, T_{\\mathrm{now}}, \\delta) $$
`;

export const MD_MERMAID = `Intro

\`\`\`mermaid
flowchart LR
  A --> B
\`\`\`
`;

export const MD_REL_LINK = `XEYO 在 [09](./09-企业级落地计划-时序与排期.md) 已定调。
`;

export const MD_LONG_CODE = `\`\`\`text
${Array.from({length: 40}, (_, i) => `line-${i}`).join('\n')}
\`\`\``;

export const MD_MIXED_EXTREME = `${MD_BASIC}

${MD_TABLE}

${MD_CODE_JS}

${MD_TASKS}

${MD_CJK}

Unclosed **bold and *italic

\`\`\`bash
echo "partial
`;
