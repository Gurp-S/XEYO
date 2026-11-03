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
| `--concurrency <n>` | max files built at once (default `8`) |
| `--watch` | build once, then rebuild whenever a source file changes |
| `--dry-run` | print the plan, write nothing (no `out/`, no manifest) |
| `--json` | print a machine-readable report on stdout |
| `--help`, `-h` | usage |

`--watch` prints one report line per build (one JSON line per build with `--json`)
and runs until `SIGINT`/`SIGTERM`. Writes are debounced and builds are serialised,
so a burst of edits collapses into a single rebuild. `--concurrency` bounds how many
outputs are written at once; it never changes the report or the output bytes.

## Output contract

Every source file under `--src` maps to `--out/<relative path>`:

| source | output |
| --- | --- |
| `*.js`, `*.mjs` | source text, trailing whitespace trimmed, plus one line `//# build <sha1-of-source-text first 8 hex>` and a final newline |
| `*.css` | source text with every `url(<target>)` rewritten to `url(<hashed name>)`; the target asset is emitted next to it as `basename.<sha1-of-bytes first 8 hex>.ext` |
| `*.json` | when the object has `"extends": "./other.json"`, the base object is merged first and the own keys override it; the `extends` key is dropped. Written as 2-space JSON plus a newline |
| anything else | copied byte for byte |

`build-manifest.json` is JSON with `{"version": 2, "files": {...}}`; each entry is
`{ "key": <source fingerprint>, "deps": { "<relative source path>": <fingerprint> }, "out": [<output relative paths>] }`.
A file is rebuilt when it has no manifest entry, its own fingerprint changed, or any recorded dependency's
fingerprint changed. Deleting a source removes its output and its manifest entry. Outputs that the manifest
claims but that are missing on disk are rebuilt, so a damaged tree heals on the next run. The manifest is
written to a temporary file and renamed into place, so an interrupted build leaves the previous manifest
intact instead of a truncated one.

Output bytes must be a pure function of source bytes: a full rebuild and an incremental rebuild from any
prior state produce identical files.

## Tests

`npm test` runs the visible tests in `tests/visible`.
