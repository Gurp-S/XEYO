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
| `--concurrency <n>` | build at most `<n>` files at once (default `1`, i.e. strictly sequential) |
| `--watch` | rebuild whenever a source file changes; runs until interrupted |
| `--json` | print a machine-readable report on stdout |
| `--help`, `-h` | usage |

`--concurrency` never changes the result: the same sources produce the same bytes and the same manifest
regardless of how many files are built at once. `--watch` polls the source tree's content (every 200 ms) instead
of listening for filesystem events, so additions, deletions and rewrites that preserve mtime are all seen. It
cannot be combined with `--dry-run`.

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
fingerprint changed. Fingerprints are content hashes, so a rewrite that keeps the size and mtime is still a
change. Dependencies are discovered from `import ... from '...'` in `*.js`/`*.mjs`, from `url(...)` in `*.css`,
and from `extends` in `*.json`.

Deleting a source removes its output and its manifest entry. The output directory is owned by the builder: a
file in it that no source claims is deleted on the next build, which is also how a build that was interrupted
before it could clean up converges. The manifest is written to a temporary file and renamed into place, so an
interrupted build leaves the previous manifest intact rather than a truncated one; a manifest that cannot be
read or does not match the expected shape is ignored and rebuilt from scratch.

Output bytes must be a pure function of source bytes: a full rebuild and an incremental rebuild from any
prior state produce identical files, including the byte order of the manifest.

## Tests

`npm test` runs the visible tests in `tests/visible`.
