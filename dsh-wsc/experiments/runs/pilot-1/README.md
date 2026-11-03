# mini-build

A tiny incremental builder for a static asset tree. Zero dependencies, Node >= 20, ESM.

```
node bin/build.js [options]
```

Options:

| option | meaning |
| --- | --- |
| `--src <dir>` | source directory (default `src`) |
| `--out <dir>` | output directory (default `out`) |
| `--manifest <file>` | build manifest path (default `build-manifest.json`) |
| `--dry-run` | print the plan, write nothing (no `out/`, no manifest) |
| `--watch` | rebuild whenever a source file changes (until interrupted) |
| `--concurrency <n>` | build at most `n` files at once (default `1`) |
| `--json` | print a machine-readable report on stdout |
| `--help`, `-h` | usage |

## Output contract

Every source file under `--src` maps to `--out/<relative path>`:

| source | output |
| --- | --- |
| `*.js`, `*.mjs` | source text, trailing whitespace trimmed, plus one line `//# build <sha1-of-source-text first 8 hex>` and a final newline |
| `*.css` | source text with every `url(<target>)` rewritten to `url(<hashed name>)`; the target asset is emitted next to the stylesheet as `basename.<sha1-of-bytes first 8 hex>.ext` |
| `*.json` | when the object has `"extends": "./other.json"`, the base object is merged first and the own keys override it; the `extends` key is dropped. Written as 2-space JSON plus a newline |
| anything else | copied byte for byte |

`build-manifest.json` is JSON with `{"version": 2, "files": {...}}`; each entry is
`{ "key": <source fingerprint>, "deps": { "<relative source path>": <fingerprint> }, "out": [<output relative paths>] }`.
Fingerprints are content hashes, so rewriting a file with the same size and mtime still invalidates it.
Dependencies are collected from JavaScript `import` specifiers, CSS `url(...)` targets, and JSON `extends`
paths. A file is rebuilt when it has no manifest entry, its own fingerprint changed, any recorded
dependency's fingerprint changed, or any output named by its manifest entry is missing. Deleting a source
removes its output and its manifest entry; outputs that are no longer produced (including superseded hashed
assets) are removed as well. The manifest is replaced atomically.

Output bytes must be a pure function of source bytes: a full rebuild and an incremental rebuild from any
prior state produce identical files.

## Tests

`npm test` runs the visible tests in `tests/visible`.
