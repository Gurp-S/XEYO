Work in this repository. The public function `buildTree` is being renamed to `compileTree`, and its module `src/tree.js` is being renamed to `src/compile-tree.js`.

Rename it everywhere it appears: the source modules, the CLI, `src/config.json`, the README, and the tests. Behaviour must not change: `compileTree(paths)` returns the same nested tree, the CLI prints the same JSON, and `src/config.json` keeps its shape.

Run `node --test tests/visible/basic.test.mjs` when you are done and report what you changed.
