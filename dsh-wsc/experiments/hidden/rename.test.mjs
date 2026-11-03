import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const root = process.env.MINI_BUILD_ROOT ?? process.cwd()

const walk = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name)
    return statSync(full).isDirectory() ? walk(full) : [full]
  })

const files = walk(root).filter((file) => !/[\\/](node_modules|\.git)[\\/]/.test(file))

test('tree.js is renamed to compile-tree.js', () => {
  assert.equal(existsSync(path.join(root, 'src', 'tree.js')), false)
  assert.equal(existsSync(path.join(root, 'src', 'compile-tree.js')), true)
})

test('no buildTree identifier remains anywhere', () => {
  const offenders = files.filter((file) => readFileSync(file, 'utf8').includes('buildTree'))
  assert.deepEqual(offenders, [])
})

test('compileTree keeps the nesting contract', async () => {
  const mod = await import(pathToFileURL(path.join(root, 'src', 'compile-tree.js')).href)
  assert.equal(typeof mod.compileTree, 'function')
  assert.deepEqual(mod.compileTree(['x/y', 'x/z']), {
    name: 'root',
    children: [{ name: 'x', children: [{ name: 'y', children: [] }, { name: 'z', children: [] }] }],
  })
})

test('every module imports the renamed entry', () => {
  for (const name of ['a', 'b', 'c', 'd', 'e', 'f']) {
    const text = readFileSync(path.join(root, 'src', `${name}.js`), 'utf8')
    assert.match(text, /from '\.\/compile-tree\.js'/)
  }
})

test('config names the renamed entry and symbol', () => {
  const config = JSON.parse(readFileSync(path.join(root, 'src', 'config.json'), 'utf8'))
  assert.equal(config.entry, 'compile-tree')
  assert.equal(config.symbol, 'compileTree')
  assert.deepEqual(config.modules, ['a', 'b', 'c', 'd', 'e', 'f'])
})

test('cli still prints every group', () => {
  const out = execFileSync(process.execPath, [path.join(root, 'bin', 'cli.js')], { encoding: 'utf8' })
  const parsed = JSON.parse(out)
  assert.deepEqual(Object.keys(parsed).sort(), ['a', 'b', 'c', 'd', 'e', 'f'])
  assert.equal(parsed.a.name, 'root')
  assert.equal(parsed.f.children[0].name, 'f')
})

test('README documents the renamed API', () => {
  const text = readFileSync(path.join(root, 'README.md'), 'utf8')
  assert.match(text, /compileTree/)
  assert.doesNotMatch(text, /buildTree/)
})
