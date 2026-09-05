---
name: tauri-specta
description: Type-safe Tauri 2 IPC with tauri-specta and specta — annotated commands, DTOs, TypeScript binding export, and frontend invoke patterns. Use when adding Tauri commands, generating bindings.ts, or refactoring invoke() to typed APIs. Triggers on tauri-specta, specta, typed IPC, bindings.ts, or type-safe Tauri commands.
---

# tauri-specta

Completely typesafe Tauri commands: Rust types drive generated TypeScript bindings.

**Crate:** `tauri-specta` + `specta`  
**Docs:** https://docs.rs/tauri-specta

## Dependencies

```bash
cargo add specta
cargo add tauri-specta --features typescript
```

Enable in `lib.rs` / `main.rs` builder as needed for your Tauri 2 setup.

## Rust: DTOs

```rust
use serde::{Deserialize, Serialize};
use specta::Type;

#[derive(Serialize, Deserialize, Type, Clone)]
#[specta(inline)]
pub struct CreateItemDto {
    pub name: String,
    pub count: i32,
}

#[derive(Serialize, Type)]
#[specta(inline)]
pub struct ItemView {
    pub id: String,
    pub name: String,
}
```

- Derive `specta::Type` on all IPC types
- Use `#[specta(inline)]` on DTOs for clean generated TS types
- Prefer structs over many positional args (max ~10 args per command)

## Rust: Commands

```rust
#[tauri::command]
#[specta::specta]
fn create_item(dto: CreateItemDto) -> Result<ItemView, String> {
    // ...
}

#[tauri::command]
#[specta::specta]
async fn list_items() -> Result<Vec<ItemView>, String> {
    // ...
}
```

Register in `generate_handler![create_item, list_items, ...]`.

## Export bindings (dev / build)

```rust
use specta::collect_types;
use tauri_specta::{collect_commands, Builder};

fn export_bindings() {
    #[cfg(debug_assertions)]
    {
        const BINDINGS: &str = "../src/bindings.ts";
        Builder::new()
            .commands(collect_commands![create_item, list_items])
            .export(
                specta_typescript::Typescript::default(),
                BINDINGS,
            )
            .unwrap();
    }
}
```

Call export once at startup in debug, or via a build script. **Do not** export into a directory watched by Tauri hot-reload (infinite reload loop).

## TypeScript usage

```typescript
import { commands } from '@/bindings'

const item = await commands.createItem({ name: 'foo', count: 1 })
const list = await commands.listItems()
```

Prefer generated `commands.*` over raw `invoke('create_item', ...)` after bindings exist.

## Tauri 2 checklist

- [ ] Every command: `#[tauri::command]` + `#[specta::specta]`
- [ ] Every DTO: `Serialize`/`Deserialize` + `Type` + `#[specta(inline)]`
- [ ] Commands listed in `collect_commands!` / export and in `generate_handler!`
- [ ] Regenerate bindings after Rust signature changes
- [ ] Frontend imports updated types from bindings file

## Error handling pattern

```rust
#[derive(Serialize, Type)]
pub struct ApiError {
    pub message: String,
}

#[tauri::command]
#[specta::specta]
fn do_work() -> Result<ItemView, ApiError> {
    // ...
}
```

Map internal errors to serializable DTOs — avoid panics across IPC.

## Known limitations

- Commands limited to ~10 arguments — use a struct
- Export path must not trigger file watcher reload loops
- Regenerate bindings in CI when Rust API changes

## References

- [tauri-specta on crates.io](https://crates.io/crates/tauri-specta)
- [specta Type derive](https://docs.rs/specta)
