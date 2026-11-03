Work in this repository. `mini-build` is a zero-dependency incremental builder for a static asset tree; `README.md` documents the output contract. Fix the reported defects, add the requested feature, and leave the whole contract holding.

Reported defects:

1. Changing an asset that a stylesheet references through `url(...)` does not rebuild the stylesheet. Changing a base file pulled in through JSON `extends` does not rebuild the derived file.
2. Rewriting a source file without changing its mtime leaves a stale output behind.
3. Deleting a source file leaves its output and its manifest entry behind, and a manifest that names outputs which no longer exist never heals.
4. A build interrupted while the manifest is being written leaves a half-written manifest that crashes the next build.

Requested feature: a `--watch` mode that rebuilds when a source changes, and a `--concurrency <n>` option that bounds how many files are built at once.

Constraints that must keep holding: the existing CLI flags and their defaults, the `version: 2` manifest shape, deterministic output order, symlink semantics, `--dry-run` writing nothing at all, zero runtime dependencies, Node >= 20 ESM.

Work in stages: read the code first, then fix the defects, then add the feature, then test your work, then report what you changed and how you verified it.
