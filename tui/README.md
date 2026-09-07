# XEYO TUI (TypeScript)

Ink + React terminal UI. Visual system follows calm TUI craft: **one teal accent + semantic states**, one rounded border language, spacing 0/1/2 — not a Claude clone.

Python remains the **engine**. This package is the **face**.

## Quick start

```powershell
cd tui
npm install
npm run demo
npm start -- --cwd D:\path\to\project   # needs: py -3.11 -m cli serve
```

## Visual flags

| Flag / env | Effect |
|---|---|
| `--no-color` / `NO_COLOR` | Strip colors (pipes/CI) |
| `--ascii` / `XEYO_ASCII=1` | ASCII glyphs, no block logo |
| narrow terminal (&lt;88 cols) | Collapses welcome to a single column |

## Design tokens

- Accent: teal (`#2DD4BF` / `cyan`)
- Success / warning / error only for state
- Status always has a glyph + word (`✓ COMPLETED`), never color alone
- Errors include a fix path (`serve` or `/demo`)
