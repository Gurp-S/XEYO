---
name: million-js
description: Million.js React performance compiler and Million Lint / React Doctor diagnostics. Use when optimizing React render performance, enabling Million automatic mode, integrating with Vite/Next, or scanning for React anti-patterns. Triggers on million.js, Million compiler, Million Lint, block virtual DOM, or React performance optimization.
---

# Million.js

Million.js is a drop-in optimizing compiler for React. It speeds up reconciliation via a block virtual DOM without rewriting your app.

**Docs:** https://million.dev  
**React Doctor (diagnostics):** see `react-doctor` skill in this project

## When to use Million.js

- Large lists, dashboards, or UI-heavy React apps with measurable render cost
- You want compiler-level optimizations without migrating frameworks
- **Not** a replacement for proper memoization, virtualization, or state design

## Installation

```bash
npm install million
```

### Vite (automatic mode)

```typescript
// vite.config.ts
import MillionLint from 'million/compiler'

export default defineConfig({
  plugins: [
    MillionLint.vite({ auto: true }),
    react(),
  ],
})
```

Automatic mode optimizes eligible components without API changes.

### Manual mode (fine-grained)

```tsx
import { block } from 'million/react'

const TableRow = block(function TableRow({ item }: { item: Item }) {
  return <tr>...</tr>
})
```

Use manual `block()` only on hot paths after profiling.

## Best practices

1. **Profile first** — use React DevTools Profiler or React Doctor trace before adding Million
2. **Keep data stable** — Million helps DOM updates; unstable props still cause work
3. **Pair with virtualization** — `@tanstack/react-virtual` for long lists; Million for per-row cost
4. **Check compatibility** — some patterns (exotic refs, certain third-party libs) may not optimize
5. **Production builds** — benchmark production, not dev (dev has extra overhead)

## React Doctor workflow (Million team)

After React changes:

```bash
npx react-doctor@latest --verbose --scope changed
```

Full codebase scan:

```bash
npx react-doctor@latest --verbose
```

Runtime performance trace (interactive):

```bash
npx react-doctor@latest scan <url> --format json
```

Install agent rules: `npx skills add millionco/react-doctor --skill react-doctor` (already in `.agents/skills/react-doctor`).

## Common pitfalls

- Expecting Million to fix fetch waterfalls or Zustand over-subscription
- Optimizing every component manually instead of automatic mode
- Measuring in dev mode and drawing conclusions
- Ignoring React Doctor regressions after enabling the compiler

## References

- [Million.js docs](https://million.dev/docs)
- [React Doctor](https://react.doctor)
