export const buildTree = (items) => {
  const root = { name: 'root', children: [] }
  for (const item of items) {
    let node = root
    for (const part of item.split('/')) {
      let child = node.children.find((entry) => entry.name === part)
      if (child === undefined) {
        child = { name: part, children: [] }
        node.children.push(child)
      }
      node = child
    }
  }
  return root
}
