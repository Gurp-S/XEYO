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
| `--concurrency <n>` | build at most `n` files at once (default 4) |
| `--watch` | keep running and rebuild whenever a source changes; `Ctrl+C` stops it |
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
A fingerprint is the SHA-1 of the file's bytes, so a rewrite with a preserved mtime still counts as a change and
a touched file with unchanged bytes does not. A file is rebuilt when it has no manifest entry, its own
fingerprint changed, any recorded dependency's fingerprint changed, or a recorded output is missing from disk.
Deleting a source removes its output and its manifest entry; outputs no source produces any more (a stale
hashed asset, for example) are removed too.

The manifest is written to a temporary file and renamed into place, so an interrupted build leaves the previous
manifest intact; the next build re-derives whatever the interrupted one did not record.

Output bytes must be a pure function of source bytes: a full rebuild and an incremental rebuild from any
prior state produce identical files.

## Tests

`npm test` runs the visible tests in `tests/visible`.
