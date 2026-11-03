import path from 'node:path';

/** True when `abs` is `root` itself, or anywhere below it. */
function withinOrSame(root, abs) {
  const rel = path.relative(root, abs);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/**
 * The set of paths the build writes itself.
 *
 * A configuration may legitimately put `--out` or the manifest inside `--src`.
 * Every consumer that looks at the source tree has to know which paths are the
 * build's own output, otherwise output is re-ingested as input: the scan would
 * copy `out/` into `out/out/`, and the watcher would rebuild forever on the
 * events its own writes produce.
 *
 * The out directory itself counts as owned, not only its descendants, because
 * creating it (`mkdir out`) emits an event on `out` whose relative path is
 * empty — the case a strict "inside" check silently misses.
 */
export function createOwned({ cwd = process.cwd(), opts }) {
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const manifestDir = path.dirname(manifestPath);
  const manifestBase = path.basename(manifestPath);

  // `saveManifest` writes `<dir>/.<name>.<pid>.<stamp>.tmp` next to the target.
  const isManifestTemp = (abs) => {
    if (path.dirname(abs) !== manifestDir) return false;
    const base = path.basename(abs);
    return base.startsWith(`.${manifestBase}.`) && base.endsWith('.tmp');
  };

  const isOwned = (abs) =>
    abs === manifestPath || withinOrSame(outDir, abs) || isManifestTemp(abs);

  return { outDir, manifestPath, isOwned };
}
