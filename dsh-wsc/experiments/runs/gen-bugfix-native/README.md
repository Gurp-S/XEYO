# slug-kit

URL slug helper. `slugify(input)` turns a title into a lowercase slug:
words separated by single dashes, ASCII letters and digits only.

    slugify('Hello, World!')  // 'hello-world'

`slugifyAll(list)` maps it over an array. The package is ESM, zero dependencies.
