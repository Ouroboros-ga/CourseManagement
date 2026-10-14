// Preserve an independently deployed Web bundle; only replace UTC string slicing.
// Usage: node build_time_hotfix.mjs BASE OUTPUT DATETIME_TS
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { createRequire } from 'node:module'
const require = createRequire(path.resolve('apps/admin-web/package.json'))
const ts = require('typescript')
const [base, output, helperPath] = process.argv.slice(2)
if (!base || !output || !helperPath || fs.existsSync(output)) throw new Error('Fresh output required')
fs.cpSync(base, output, { recursive: true })
const helper = ts.transpileModule(fs.readFileSync(helperPath, 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }
}).outputText.replace('export function formatBeijingTime', 'function __cmBeijingTime')
const assets = path.join(base, 'assets')
const replacements = new Map()
const details = []
for (const name of fs.readdirSync(assets).filter(n => /^(ObjectionsView|TaskListView)-.*\.js$/.test(n))) {
  const source = fs.readFileSync(path.join(assets, name), 'utf8')
  const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
  const edits = []
  function visit(node) {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
      && node.expression.name.text === 'replace' && node.arguments.length === 2
      && node.arguments[0].text === 'T' && node.arguments[1].text === ' ') {
      const sliced = node.expression.expression
      if (ts.isCallExpression(sliced) && ts.isPropertyAccessExpression(sliced.expression)
        && sliced.expression.name.text === 'substring' && sliced.arguments.length === 2) {
        const start = sliced.arguments[0].getText(tree), end = sliced.arguments[1].getText(tree)
        if ((start === '0' || start === '5') && (end === '16' || end === '19')) {
          const value = sliced.expression.expression.getText(tree)
          edits.push({ start: node.getStart(tree), end: node.end,
            value: `__cmBeijingTime(${value},"${start === '5' ? 'short' : end === '16' ? 'minute' : 'full'}")` })
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(tree)
  if (!edits.length) continue
  let patched = source
  for (const edit of edits.sort((a, b) => b.start - a.start)) {
    patched = patched.slice(0, edit.start) + edit.value + patched.slice(edit.end)
  }
  patched += '\n' + helper
  const target = name.replace(/\.js$/, '-pt20261014r2.js')
  fs.writeFileSync(path.join(output, 'assets', target), patched)
  replacements.set(name, target)
  details.push({ name, target, timestamp_sites: edits.length,
    baseline_sha256: crypto.createHash('sha256').update(source).digest('hex') })
}
if (details.length !== 2 || details.reduce((n, d) => n + d.timestamp_sites, 0) !== 7) {
  throw new Error('Unexpected deployed timestamp call sites; inspect baseline')
}
// Cascade new names through the import graph, retaining old assets for open tabs.
let changed = true
while (changed) {
  changed = false
  for (const name of fs.readdirSync(assets).filter(n => n.endsWith('.js'))) {
    if (replacements.has(name)) continue
    const source = fs.readFileSync(path.join(assets, name), 'utf8')
    let patched = source
    for (const [oldName, newName] of replacements) patched = patched.replaceAll(oldName, newName)
    if (patched !== source) {
      const target = name.replace(/\.js$/, '-pt20261014r2.js')
      fs.writeFileSync(path.join(output, 'assets', target), patched)
      replacements.set(name, target)
      changed = true
    }
  }
}
// All new modules must import the new graph, including leaf bundles created first.
for (const target of replacements.values()) {
  const location = path.join(output, 'assets', target)
  let source = fs.readFileSync(location, 'utf8')
  for (const [oldName, newName] of replacements) source = source.replaceAll(oldName, newName)
  fs.writeFileSync(location, source)
}
let html = fs.readFileSync(path.join(base, 'index.html'), 'utf8')
for (const [oldName, newName] of replacements) html = html.replaceAll(oldName, newName)
fs.writeFileSync(path.join(output, 'index.html'), html)
fs.writeFileSync(path.join(output, 'PHOTO_TIME_MANIFEST.json'), JSON.stringify({
  preserved_release: JSON.parse(fs.readFileSync(path.join(base, 'RELEASE_MANIFEST.json'), 'utf8')).commit,
  helper_sha256: crypto.createHash('sha256').update(fs.readFileSync(helperPath)).digest('hex'),
  details, renamed_imports: Object.fromEntries(replacements)
}, null, 2))
console.log(JSON.stringify({ timestamp_sites: 7, modified_bundles: details, import_updates: replacements.size }))
