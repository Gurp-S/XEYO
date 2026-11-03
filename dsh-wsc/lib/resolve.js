import { createRequire } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const cache = new Map()

/**
 * Load a package that ships with the running Harness.
 *
 * A profile plugin lives outside the installation, so a bare specifier does not
 * resolve from its own directory. The installed Harness is authoritative: try
 * the normal resolution first (CLI/TUI checkouts), then resolve against the
 * Desktop runtime manifest and import the exact file the Host itself loaded.
 *
 * @param {string} specifier bare package name.
 * @returns {Promise<Record<string, unknown>>} the loaded module namespace.
 */
export function loadDshPackage(specifier) {
  const cached = cache.get(specifier)
  if (cached !== undefined) return cached

  const loading = (async () => {
    try {
      return await import(specifier)
    } catch (firstError) {
      const manifest = process.resourcesPath
        ? join(process.resourcesPath, 'app.asar', 'dsh', 'package.json')
        : undefined
      if (manifest === undefined) throw firstError
      const requireFromDsh = createRequire(manifest)
      const resolved = requireFromDsh.resolve(specifier)
      return await import(pathToFileURL(resolved).href)
    }
  })()

  cache.set(specifier, loading)
  return loading
}
