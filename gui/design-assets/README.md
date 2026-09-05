# Design / deferred assets (not shipped in production UI bundle)

Pasture mockups and oversized island art live here so `public/` (→ `dist/` → Tauri) stays lean while Context Island is render-gated off.

- `pasture-refs/` — design sheets & scene comps (were unused at runtime)
- Island `character.svg` is still under `public/` for when the island flag is re-enabled, but the Vite build plugin strips it from `dist` unless `VITE_XY_CONTEXT_ISLAND=1`.
