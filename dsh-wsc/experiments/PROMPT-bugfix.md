Work in this repository. `slug-kit` turns titles into URL slugs; `README.md` documents the contract.

Reported defects in `slugify`:

1. Runs of spaces or dashes survive: `slugify('a   b')` returns `a---b` instead of one dash.
2. Leading and trailing separators survive: `slugify('--x--')` returns `--x--`.
3. Accented letters are dropped instead of transliterated: `slugify('Über Café')` returns `ber-caf`.
4. Underscores and other symbols are deleted instead of acting as separators: `slugify('A_B')` returns `ab`.
5. Input made only of separators should produce an empty string.

Keep the public API (`slugify`, `slugifyAll`), the ESM layout, and the zero-dependency rule.
Run `node --test tests/visible/basic.test.mjs` when you are done and report what you changed.
