# slug-kit

URL slug helper. `slugify(input)` turns a title into a lowercase slug:
words separated by single dashes, ASCII letters and digits only.

    slugify('Hello, World!')  // 'hello-world'
    slugify('Über Café')      // 'uber-cafe'
    slugify('--x--')          // 'x'

Any run of characters that is not an ASCII letter or digit (spaces, dashes,
underscores, punctuation, symbols) is a single word boundary, so it becomes one
dash; boundaries at the start or end of the input are dropped. Accented letters
are transliterated to their ASCII base letter rather than discarded, and input
with no words at all yields `''`.

`slugifyAll(list)` maps it over an array. The package is ESM, zero dependencies.
