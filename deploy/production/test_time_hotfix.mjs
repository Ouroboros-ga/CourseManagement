import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import vm from 'node:vm'
const output = process.argv[2]
const manifest = JSON.parse(fs.readFileSync(path.join(output, 'PHOTO_TIME_MANIFEST.json'), 'utf8'))
for (const target of Object.values(manifest.renamed_imports)) {
  const source = fs.readFileSync(path.join(output, 'assets', target), 'utf8')
  for (const oldName of Object.keys(manifest.renamed_imports)) {
    assert.ok(!source.includes(oldName), `${target} still imports ${oldName}`)
  }
}
for (const detail of manifest.details) {
  const source = fs.readFileSync(path.join(output, 'assets', detail.target), 'utf8')
  const helper = source.slice(source.lastIndexOf('\nfunction __cmBeijingTime'))
  assert.equal(vm.runInNewContext(helper + ';__cmBeijingTime("2026-10-14T04:29:06")'),
    '2026-10-14 12:29:06')
}
console.log('Import graph and deployed helper checks passed')
