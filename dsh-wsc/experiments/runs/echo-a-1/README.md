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
| `--concurrency <n>` | build at most `n` files at once (default `4`) |
| `--watch` | rebuild whenever a source changes |
| `--dry-run` | print the plan, write nothing (no `out/`, no manifest) |
| `--json` | print a machine-readable report on stdout |
| `--help`, `-h` | usage |

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
fingerprint changed. Deleting a source removes its output and its manifest entry.

Output bytes must be a pure function of source bytes: a full rebuild and an incremental rebuild from any
prior state produce identical files.

## Watch mode

`--watch` builds once, then rebuilds on any change under `--src`. Changes are debounced, so a burst of
edits produces one rebuild; a failing build reports its error and keeps watching. Files written by the
build itself never trigger a rebuild. `--dry-run` and `--watch` are mutually exclusive.

## Report

Each build prints one line, `built <n>, skipped <n>, removed <n> in <ms>ms`; `--json` prints the same
report as one JSON object.

## Tests

`npm test` runs the visible tests in `tests/visible`.
