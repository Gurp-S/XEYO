---
name: zustand
description: Expert guidance for Zustand state management in React and Next.js — store design, selectors, middleware (persist/devtools), performance, and testing. Use when working with Zustand, create store, useStore, persist middleware, or client state in this project.
---

# Zustand State Management

You are an expert in Zustand state management for React and Next.js applications.

## Core Principles

- Use Zustand for lightweight, flexible **shared client state**
- Minimize `useEffect` and `setState`; prioritize derived state and memoization
- Implement functional, declarative patterns — avoid classes
- Use descriptive variable names with auxiliary verbs like `isLoading`, `hasError`
- Do **not** use Zustand for server/async cache — use TanStack Query (or similar) for that

## Store Design

### Basic Store Structure

```typescript
import { create } from 'zustand'

interface BearState {
  bears: number
  isLoading: boolean
  hasError: boolean
  increase: () => void
  reset: () => void
}

const useBearStore = create<BearState>((set) => ({
  bears: 0,
  isLoading: false,
  hasError: false,
  increase: () => set((state) => ({ bears: state.bears + 1 })),
  reset: () => set({ bears: 0 }),
}))
```

### Best Practices

- Keep stores focused and domain-specific (one store per domain)
- Use selectors to prevent unnecessary re-renders
- Implement middleware for persistence, logging, or devtools
- Separate actions from state when stores grow complex
- Prefer `set((state) => ({ ... }))` for updates that depend on prior state

## Integration with React

```typescript
// Select a single field — component re-renders only when bears changes
const bears = useBearStore((s) => s.bears)

// Select multiple fields with shallow compare
import { useShallow } from 'zustand/react/shallow'
const { bears, increase } = useBearStore(
  useShallow((s) => ({ bears: s.bears, increase: s.increase })),
)
```

- Use shallow equality when selecting multiple values
- Combine with TanStack Query for server state
- Implement proper TypeScript interfaces for type safety
- Avoid selecting the entire store: `useStore()` without a selector

## Performance Optimization

- Select only the state you need in components
- Use `useShallow` (or individual selectors) for object selections
- Memoize computed/derived values outside the store when they are expensive
- Keep action references stable — define actions inside `create`, not recreated per render

## Middleware Usage

### Persistence

```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const useStore = create(
  persist(
    (set) => ({
      count: 0,
      increment: () => set((s) => ({ count: s.count + 1 })),
    }),
    { name: 'store-key' },
  ),
)
```

### DevTools

```typescript
import { devtools } from 'zustand/middleware'

const useStore = create(
  devtools(
    (set) => ({
      // state and actions
    }),
    { name: 'MyStore' },
  ),
)
```

### Combining middleware (order matters: devtools wraps persist wraps store)

```typescript
const useStore = create(
  devtools(
    persist(
      (set) => ({ /* ... */ }),
      { name: 'app-settings' },
    ),
    { name: 'SettingsStore' },
  ),
)
```

## TypeScript (v5)

```typescript
import { create } from 'zustand'

type State = {
  count: number
  increment: () => void
}

export const useCounterStore = create<State>()((set) => ({
  count: 0,
  increment: () => set((s) => ({ count: s.count + 1 })),
}))
```

Note the **double parentheses** `create<State>()((set) => ...)` when using middleware type inference.

## Error Handling

- Handle errors at function start using early returns and guard clauses
- Implement error states within stores (`hasError`, `errorMessage`)
- Use try/catch in async actions; set loading/error flags in the same action
- Provide meaningful error messages

## Testing

- Test stores independently of components (`useStore.getState()`, `useStore.setState()`)
- Reset store state between tests: `useStore.setState(initialState, true)` (replace mode)
- Mock Zustand stores in component tests when needed
- Verify state transitions and actions
- Test middleware behavior separately

## Common Pitfalls

- Selecting entire store object → re-renders on any field change
- Inline selector functions that return new object literals every call without `useShallow`
- Storing server-fetched data that should live in a query cache
- Forgetting to handle persist hydration flash in SSR/Next.js
- Unmemoized `getItemKey`-style patterns when deriving lists from store state

## References

- [Zustand docs](https://zustand.docs.pmnd.rs)
- [GitHub — pmndrs/zustand](https://github.com/pmndrs/zustand)
