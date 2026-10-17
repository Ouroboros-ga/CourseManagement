import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse, compileTemplate } from '@vue/compiler-sfc'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '../src')
const ELEMENT = 1, TEXT = 2, COMMENT = 3, IF = 9, FOR = 10

function walk(node, visit) {
  if (!node || typeof node !== 'object') return
  visit(node)
  for (const key of ['children', 'branches']) {
    for (const child of node[key] || []) walk(child.type === undefined ? child : child, visit)
  }
  if (node.content) walk(node.content, visit)
}

function templateAst(file) {
  const { descriptor } = parse(readFileSync(file, 'utf8'), { filename: file })
  if (!descriptor.template) return null
  return compileTemplate({ source: descriptor.template.content, filename: file, id: 'scan' }).ast
}

function meaningful(children = []) {
  return children.filter(node => node.type !== COMMENT && !(node.type === TEXT && !node.value.trim()))
}

function importsOf(file) {
  const source = readFileSync(file, 'utf8')
  const map = new Map()
  for (const match of source.matchAll(/import\s+([A-Za-z0-9_]+)\s+from\s+['"]([^'"]+)['"]/g)) {
    const specifier = match[2]
    if (!specifier.startsWith('.')) continue
    const target = resolve(dirname(file), specifier.endsWith('.vue') ? specifier : `${specifier}.vue`)
    if (exists(target)) map.set(match[1], target)
  }
  return map
}
function exists(file) {
  try { return statSync(file).isFile() } catch { return false }
}

/** Vue resolves a component's transition target down to its single root element. */
function rootKind(file, imports = importsOf(file), depth = 0) {
  if (depth > 6) return { ok: true, note: 'depth-limit' }
  const ast = templateAst(file)
  if (!ast) return { ok: true, note: 'no-template' }
  const roots = meaningful(ast.children)
  if (roots.length !== 1) return { ok: false, roots: roots.length }
  const [root] = roots
  if (root.type === IF) {
    for (const branch of root.branches || []) {
      const branchRoots = meaningful(branch.children)
      if (branchRoots.length !== 1) return { ok: false, roots: branchRoots.length }
      const nested = describe(branchRoots[0], file, imports, depth)
      if (!nested.ok) return nested
    }
    return { ok: true }
  }
  return describe(root, file, imports, depth)
}

function describe(node, file, imports, depth) {
  if (node.type !== ELEMENT) return { ok: false, roots: `non-element:${node.type}` }
  const target = imports.get(node.tag)
  if (!target) return { ok: true }
  return rootKind(target, imports, depth + 1)
}

function collectTransitions(root = SRC, found = []) {
  for (const entry of readdirSync(root)) {
    const full = resolve(root, entry)
    if (statSync(full).isDirectory()) collectTransitions(full, found)
    else if (entry.endsWith('.vue')) found.push(full)
  }
  return found
}

test('every out-in transition child has a single element root', () => {
  const offenders = []
  for (const file of collectTransitions()) {
    const ast = templateAst(file)
    if (!ast) continue
    const imports = importsOf(file)
    walk(ast, node => {
      if (node.type !== ELEMENT || !/^[Tt]ransition$/.test(node.tag)) return
      const mode = (node.props || []).find(prop => prop.type === 6 && prop.name === 'mode')
      if (mode?.value?.content !== 'out-in') return
      const children = meaningful(node.children)
      const branches = children.flatMap(child => child.type === IF ? (child.branches || []) : [null])
      for (const branch of branches) {
        for (const child of meaningful(branch?.children || children)) {
          const verdict = child.type === ELEMENT
            ? (imports.has(child.tag) ? rootKind(imports.get(child.tag), imports) : { ok: true })
            : { ok: true }
          if (!verdict.ok) offenders.push(`${file.replace(SRC, 'src')} <${child.tag}> roots=${verdict.roots}`)
        }
      }
    })
  }
  assert.deepEqual(offenders, [], `Multi-root components cannot be animated by <Transition mode="out-in">:\n${offenders.join('\n')}`)
})
