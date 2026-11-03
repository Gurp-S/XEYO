# rename-fixture

A tiny tree builder. The public entry point is `compileTree`, exported from
`src/compile-tree.js`. `compileTree(paths)` splits each path on `/` and nests the
segments under a single root node named `root`; sibling segments keep the
order they first appear in.

`src/config.json` names the entry module and the exported symbol. Every module
in `src/` imports the entry point, and `src/registry.js` collects the six
groups into one object. `bin/cli.js` prints the registry as JSON.

Run the tests with `node --test tests/visible/basic.test.mjs`.
