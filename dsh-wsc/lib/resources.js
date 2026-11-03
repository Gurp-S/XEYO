/**
 * Bounded object I/O and installation-time path leases, ported from XENYON
 * `wsc/resource_io.py`.
 *
 * A lease is an identity lease, not a lock: JavaScript cannot set a Windows
 * share mode, so the lease records the identity (volume/file index, size and
 * mtime) of every named object and of every parent directory, holds the file
 * handles open, and fails closed if any of them changed before installation.
 * `checkEvidence` is the re-check that runs against those recorded digests.
 */
import { createHash, randomBytes } from 'node:crypto'
import {
  closeSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readSync,
  statSync,
  unlinkSync,
  writeSync,
} from 'node:fs'
import { dirname, join, parse, resolve } from 'node:path'

/** @param {string} code @returns {never} */
const fail = (code) => {
  throw new Error(code)
}

const isLink = (info) => info.isSymbolicLink()

/** @param {string} path @returns {string[]} every ancestor of a path, nearest last. */
const ancestors = (path) => {
  const result = []
  let current = dirname(resolve(path))
  const root = parse(current).root
  while (current !== root) {
    result.push(current)
    current = dirname(current)
  }
  return result
}

/** @param {string} path @returns {string} the identity key of an object. */
const identity = (info) => `${info.dev}:${info.ino}`

/** @param {string} path */
const identityOf = (path) => lstatSync(path, { bigint: true })

export class ResourceIO {
  /**
   * @param {{ chunkBytes?: number, syncDirectory?: boolean, maxOpenHandles?: number }} [options]
   */
  constructor(options = {}) {
    this.chunkBytes = options.chunkBytes ?? 65_536
    this.syncDirectory = options.syncDirectory ?? false
    this.maxOpenHandles = options.maxOpenHandles ?? 4096
    if (!Number.isInteger(this.chunkBytes) || this.chunkBytes <= 0) fail('resource_chunk_budget_invalid')
    if (typeof this.syncDirectory !== 'boolean') fail('resource_sync_policy_invalid')
    if (!Number.isInteger(this.maxOpenHandles) || this.maxOpenHandles <= 0) fail('resource_handle_budget_invalid')
    this.bytesRead = 0
  }

  /**
   * Run `fn` on an opened object and prove afterwards that the same object is
   * still there. A link leaf is never followed, and a directory is pinned by
   * identity only, because Windows cannot open one as a plain stream here.
   *
   * @param {string} path object to open.
   * @param {{ directory?: boolean }} [options]
   * @param {(fd: number|undefined) => any} fn body.
   * @returns {any} the body result.
   */
  withOpened(path, options, fn) {
    const directory = options?.directory === true
    const body = typeof options === 'function' ? options : fn
    const before = identityOf(path)
    if (isLink(before)) fail('evidence_path_symlink')
    if (directory ? !before.isDirectory() : !before.isFile()) fail('evidence_resource_not_regular')
    let fd
    try {
      if (!directory) fd = openSync(path, 'r')
      const result = body(fd)
      const after = identityOf(path)
      if (identity(before) !== identity(after)) fail('evidence_resource_changed')
      if (!directory && (after.size !== before.size || after.mtimeNs !== before.mtimeNs)) fail('evidence_resource_changed')
      return result
    } finally {
      if (fd !== undefined) closeSync(fd)
    }
  }

  /**
   * Compare an object with bytes in bounded chunks.
   *
   * @param {string} path
   * @param {Buffer} payload
   * @returns {boolean}
   */
  equal(path, payload) {
    return this.withOpened(path, (fd) => {
      const size = statSync(path).size
      if (size !== payload.length) return false
      const buffer = Buffer.alloc(this.chunkBytes)
      let offset = 0
      for (;;) {
        const readBytes = readSync(fd, buffer, 0, this.chunkBytes, offset)
        if (readBytes === 0) return offset === payload.length
        this.bytesRead += readBytes
        if (!buffer.subarray(0, readBytes).equals(payload.subarray(offset, offset + readBytes))) return false
        offset += readBytes
      }
    })
  }

  /**
   * Digest an object under a byte budget and an optional deadline.
   *
   * @param {string} path
   * @param {{ maxBytes?: number|null, deadline?: number|null }} [options]
   * @returns {string} lowercase hex sha256.
   */
  digest(path, options = {}) {
    const maxBytes = options.maxBytes ?? null
    const deadline = options.deadline ?? null
    if (maxBytes !== null && (!Number.isInteger(maxBytes) || maxBytes < 0)) fail('resource_read_budget_invalid')
    if (deadline !== null && typeof deadline !== 'number') fail('resource_read_deadline_invalid')
    return this.withOpened(path, (fd) => {
      const hasher = createHash('sha256')
      const buffer = Buffer.alloc(this.chunkBytes)
      let total = 0
      for (;;) {
        if (deadline !== null && Date.now() > deadline) fail('resource_read_deadline_exceeded')
        const want = maxBytes === null ? this.chunkBytes : Math.min(this.chunkBytes, maxBytes - total + 1)
        if (want <= 0) fail('reference_resource_changed')
        const readBytes = readSync(fd, buffer, 0, want, total)
        if (readBytes === 0) break
        this.bytesRead += readBytes
        total += readBytes
        if (maxBytes !== null && total > maxBytes) fail('reference_resource_changed')
        hasher.update(buffer.subarray(0, readBytes))
      }
      return hasher.digest('hex')
    })
  }

  /**
   * Read at most `maxBytes` of an object.
   *
   * @param {string} path
   * @param {number} maxBytes
   * @param {{ deadline?: number|null }} [options]
   * @returns {Buffer}
   */
  readBounded(path, maxBytes, options = {}) {
    const deadline = options.deadline ?? null
    if (!Number.isInteger(maxBytes) || maxBytes < 0) fail('resource_read_budget_invalid')
    if (deadline !== null && typeof deadline !== 'number') fail('resource_read_deadline_invalid')
    return this.withOpened(path, (fd) => {
      const chunks = []
      let remaining = maxBytes
      const buffer = Buffer.alloc(this.chunkBytes)
      while (remaining > 0) {
        if (deadline !== null && Date.now() > deadline) fail('resource_read_deadline_exceeded')
        const want = Math.min(this.chunkBytes, remaining)
        const readBytes = readSync(fd, buffer, 0, want, maxBytes - remaining)
        if (readBytes === 0) break
        this.bytesRead += readBytes
        chunks.push(Buffer.from(buffer.subarray(0, readBytes)))
        remaining -= readBytes
      }
      return Buffer.concat(chunks)
    })
  }

  /** @returns {object} what this platform can actually guarantee. */
  capabilities() {
    return {
      atomic_no_replace_publication: true,
      file_fsync: true,
      directory_fsync_requested: this.syncDirectory,
      directory_fsync_platform_path: process.platform !== 'win32',
      directory_fsync_verified: false,
      windows_directory_durability_verified: false,
      installation_path_leases: process.platform === 'win32' ? 'identity' : false,
      power_loss_recovery_proven: false,
      max_lease_handles: this.maxOpenHandles,
    }
  }

  /**
   * Publish an object without ever replacing an existing one: write a pending
   * file, fsync it, then link it into place, which fails if the name is taken.
   *
   * @param {string} path destination.
   * @param {Buffer} payload bytes.
   */
  writeOnce(path, payload) {
    if (this.syncDirectory && process.platform === 'win32') fail('directory_sync_unavailable')
    mkdirSync(dirname(path), { recursive: true })
    try {
      if (this.equal(path, payload)) return
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    const pending = join(dirname(path), `.pending-${randomBytes(8).toString('hex')}`)
    const fd = openSync(pending, 'wx')
    try {
      writeSync(fd, payload)
      fsyncSync(fd)
    } finally {
      closeSync(fd)
    }
    try {
      try {
        linkSync(pending, path)
      } catch (error) {
        if (error?.code !== 'EEXIST') throw error
        if (!this.equal(path, payload)) fail('evidence_object_conflict')
      }
    } finally {
      try {
        unlinkSync(pending)
      } catch {
        // The pending name is already gone; nothing to clean up.
      }
    }
  }

  /**
   * Memoize a writer while the handles it opened still pin the objects.
   *
   * @returns {{ write: (path: string, payload: Buffer) => void, close: () => void }}
   */
  publicationWriter() {
    const cache = new Map()
    const handles = []
    return {
      write: (path, payload) => {
        const signature = `${payload.length}:${createHash('sha256').update(payload).digest('hex')}`
        if (cache.has(path)) {
          if (cache.get(path) !== signature) fail('evidence_object_conflict')
          return
        }
        this.writeOnce(path, payload)
        if (process.platform !== 'win32' || cache.size >= Math.min(128, this.maxOpenHandles)) return
        handles.push(openSync(path, 'r'))
        cache.set(path, signature)
      },
      close: () => {
        for (const fd of handles) closeSync(fd)
        handles.length = 0
      },
    }
  }

  /**
   * Take an identity lease over every object a package names.
   *
   * @param {object} package publication package.
   * @returns {{ paths: string[], directories: string[], verify: () => void, release: () => void }}
   */
  lease(package_) {
    if (process.platform !== 'win32') fail('installation_resource_lease_unavailable')
    const paths = collectPaths(package_)
    const directories = new Set()
    for (const path of paths) for (const parent of ancestors(path)) directories.add(parent)
    if (paths.size + directories.size > this.maxOpenHandles) fail('installation_resource_budget_exhausted')

    const entries = []
    const record = (path, directory) => {
      let info
      try {
        info = identityOf(path)
      } catch {
        fail('installation_resource_unavailable')
      }
      if (isLink(info)) fail('evidence_path_symlink')
      if (directory ? !info.isDirectory() : !info.isFile()) fail('evidence_resource_not_regular')
      entries.push({ path, directory, info })
    }
    for (const directory of [...directories].sort((a, b) => a.split(/[\\/]/).length - b.split(/[\\/]/).length || (a < b ? -1 : 1))) {
      record(directory, true)
    }
    for (const path of [...paths].sort()) record(path, false)

    const verify = () => {
      for (const entry of entries) {
        let info
        try {
          info = identityOf(entry.path)
        } catch {
          fail('installation_resource_unavailable')
        }
        if (identity(entry.info) !== identity(info)) fail('evidence_resource_changed')
        if (!entry.directory && (info.size !== entry.info.size || info.mtimeNs !== entry.info.mtimeNs)) {
          fail('evidence_resource_changed')
        }
      }
    }
    return { paths: [...paths], directories: [...directories], verify, release: () => {} }
  }
}

/**
 * Every object a package names, mirroring the reference collector: exported
 * evidence locators, projection evidence, the two indexes, and reference
 * bindings that claim a unique content match.
 *
 * @param {object} package publication package.
 * @returns {Set<string>} absolute paths.
 */
export function collectPaths(package_) {
  const paths = new Set()
  const collect = (value) => {
    if (value === null || typeof value !== 'object') return
    if (Array.isArray(value)) {
      for (const nested of value) collect(nested)
      return
    }
    for (const key of ['file_path', 'readable_path']) {
      if (typeof value[key] === 'string') paths.add(resolve(value[key]))
    }
    for (const nested of Object.values(value)) collect(nested)
  }
  collect(package_?.evidence)
  collect(package_?.excerpt_evidence)
  collect(package_?.adapter?.projection_evidence)
  for (const key of ['source_index', 'understanding_index']) {
    if (typeof package_?.[key] === 'string') paths.add(resolve(package_[key]))
  }
  for (const binding of package_?.current_reference_bindings ?? []) {
    if (binding?.status === 'unique_content_match' && typeof binding.resource === 'string') {
      paths.add(resolve(binding.resource))
    }
  }
  return paths
}

/**
 * Re-check every exported object against the digest the package recorded.
 *
 * @param {ResourceIO} io bounded reader.
 * @param {object} package publication package.
 */
export function checkEvidence(io, package_) {
  const projection = package_?.adapter?.projection_evidence
  if (projection !== undefined && projection !== null) {
    if (io.digest(projection.file_path) !== projection.sha256) fail('exported_projection_index_changed')
  }
  for (const [key, locator] of Object.entries(package_?.evidence ?? {})) {
    let isFile = false
    try {
      isFile = lstatSync(locator.file_path).isFile()
    } catch {
      isFile = false
    }
    if (!isFile) fail('exported_source_unavailable')
    if (io.digest(locator.file_path) !== locator.sha256) fail('exported_source_changed')
    if (typeof locator.readable_path === 'string') {
      if (io.digest(locator.readable_path) !== locator.readable_sha256) fail('exported_readable_changed')
    }
  }
  for (const key of ['source_index', 'understanding_index']) {
    const path = package_?.[key]
    if (typeof path !== 'string') continue
    if (io.digest(path) !== package_?.[`${key}_sha256`]) fail('exported_index_changed')
  }
}
