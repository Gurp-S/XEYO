// A/B check: does a change to a file referenced from CSS dirty the stylesheet?
// Usage: node tests/ab/css-dep.mjs <old|new>
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const variant = process.argv[2];
// "old" runs a snapshot of the pre-fix resolver next to the current build code,
// so both variants share every other line.
const libFile = variant === 'old' ? 'tests/ab/old/lib/build.js' : 'lib/build.js';
const { build, DEFAULT_MANIFEST, DEFAULT_OUT, DEFAULT_SRC } = await import(
  pathToFileURL(path.join(root, libFile)).href
);
const work = path.join(root, 'tests/ab/.work-' + variant);

await rm(work, { recursive: true, force: true });
await mkdir(work, { recursive: true });
await cp(path.join(root, 'src'), path.join(work, DEFAULT_SRC), { recursive: true });
const opts = { src: DEFAULT_SRC, out: DEFAULT_OUT, manifest: DEFAULT_MANIFEST, concurrency: 4 };

await build(opts, work);
const firstCss = await readFile(path.join(work, DEFAULT_OUT, 'style.css'), 'utf8');
const firstUrl = /url\(([^)]+)\)/.exec(firstCss)?.[1];

await writeFile(path.join(work, DEFAULT_SRC, 'img.png'), Buffer.from('changed-image-bytes'));
const report = await build(opts, work);

const css = await readFile(path.join(work, DEFAULT_OUT, 'style.css'), 'utf8');
const url = /url\(([^)]+)\)/.exec(css)?.[1];
const outNames = await readdir(path.join(work, DEFAULT_OUT));
const manifest = JSON.parse(await readFile(path.join(work, DEFAULT_MANIFEST), 'utf8'));

console.log(
  JSON.stringify(
    {
      variant,
      rebuilt: report.built,
      cssUrlBefore: firstUrl,
      cssUrlAfter: url,
      cssPointsAtExistingFile: outNames.includes(url),
      staleAssetLeftBehind: firstUrl !== url && outNames.includes(firstUrl),
      manifestDeps: manifest.files['style.css'].deps,
      out: outNames.sort(),
    },
    null,
    2,
  ),
);
