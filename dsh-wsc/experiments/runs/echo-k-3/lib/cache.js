// Compatibility surface for the old cache module. Fingerprints used to be
// `size:mtime`, which missed same-size rewrites and rebuilt untouched files.
// They are content hashes now; callers that still import `cacheKey` keep working.
export { contentKey as cacheKey } from './hash.js';
