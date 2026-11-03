import test from 'node:test'
import assert from 'node:assert/strict'
import { compileTree } from '../../src/compile-tree.js'
import { groups } from '../../src/registry.js'

test('compileTree nests paths under one root', () => {
  assert.deepEqual(compileTree(['x/y', 'x/z']), {
    name: 'root',
    children: [{ name: 'x', children: [{ name: 'y', children: [] }, { name: 'z', children: [] }] }],
  })
})

test('every group builds a tree named after its group', () => {
  for (const [name, build] of Object.entries(groups)) {
    const tree = build()
    assert.equal(tree.name, 'root')
    assert.equal(tree.children.length, 1)
    assert.equal(tree.children[0].name, name)
  }
})
