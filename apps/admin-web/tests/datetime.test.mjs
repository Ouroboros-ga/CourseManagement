import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const source = await readFile(new URL('../src/utils/datetime.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { formatBeijingTime } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('UTC timestamps show Beijing time including day rollover', () => {
  assert.equal(formatBeijingTime('2026-10-14T04:29:06'), '2026-10-14 12:29:06')
  assert.equal(formatBeijingTime('2026-10-14T20:29:06Z'), '2026-10-15 04:29:06')
})
test('explicit offsets are respected without double conversion', () => {
  assert.equal(formatBeijingTime('2026-10-14T12:29:06+08:00'), '2026-10-14 12:29:06')
  assert.equal(formatBeijingTime('2026-10-14T04:29:06+0000', 'short'), '10-14 12:29')
})
test('missing or invalid timestamps do not manufacture times; dates stay dates', () => {
  assert.equal(formatBeijingTime(null), '-')
  assert.equal(formatBeijingTime('bad'), '-')
  assert.equal(formatBeijingTime('2026-10-14'), '2026-10-14')
})
