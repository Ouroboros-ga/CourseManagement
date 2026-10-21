import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function load(file, imports = {}) {
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, { module, exports: module.exports, require: name => imports[name], Date, Intl })
  return module.exports
}
const datetime = load('../src/utils/datetime.ts')
const { staffRecordTime } = load('../src/utils/staffRecordTime.ts', { './datetime': datetime })
test('teacher task UTC timestamps display the frozen Beijing time exactly once', () => {
  const task = { starts_at: '2026-10-21T10:50:00+00:00', ends_at: '2026-10-21T12:25:00+00:00', inspection_date: '2026-10-21' }
  assert.equal(staffRecordTime(task), '2026-10-21 18:50 — 2026-10-21 20:25')
  assert.equal(staffRecordTime({ ...task, starts_at: '2026-10-21T18:50:00+08:00', ends_at: '2026-10-21T20:25:00+08:00' }), staffRecordTime(task))
  assert.equal(staffRecordTime({ inspection_date: '2026-10-21' }), '2026-10-21')
})
