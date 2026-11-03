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
| `--json` | print a machine-readable report on stdout |
| `--watch` | rebuild whenever a source changes, until interrupted |
| `--concurrency <n>` | build at most `<n>` files at once (default `1`) |
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
A dependency is the target of an `*.js`/`*.mjs` import, a `*.css` `url(...)`, or a `*.json` `extends`.
A file is rebuilt when it has no manifest entry, its own fingerprint changed, any recorded dependency's
fingerprint changed, or one of its recorded outputs is missing. Fingerprints are content hashes rather
than timestamps, so rewriting a file without changing its size or mtime still rebuilds it. Deleting a
source removes its output and its manifest entry.

The manifest is replaced atomically, and a manifest that cannot be read or does not have the expected
shape is treated as absent: the build rebuilds everything and rewrites it instead of failing.

Output bytes must be a pure function of source bytes: a full rebuild and an incremental rebuild from any
prior state produce identical files. `--concurrency` bounds how many files are rendered and written at
once and changes nothing about the result.

`--watch` runs an initial build, then rebuilds on every change under `--src`, printing a report per
build. With `--json`, stdout carries only JSON reports and the notices go to stderr. The process exits on
`SIGINT`/`SIGTERM`.

## Tests

`npm test` runs the visible tests in `tests/visible`.
