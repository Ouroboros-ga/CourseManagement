import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function fixture(scoped) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL('../src/utils/period.ts', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports,
    require: () => ({ isAcademicScoped: () => scoped }) })
  return module.exports
}

test('configured period identifiers never expand through the old six-slot mapping', () => {
  assert.equal(fixture(true).formatPeriodText(1, 1), '第 1 节')
  assert.equal(fixture(true).formatPeriodText(5, 6), '第 5-6 节')
  assert.equal(fixture(true).formatPeriodText(20, 23), '第 20-23 节')
  assert.equal(fixture(true).getPeriodTimeRange(1, 1), '')
  assert.equal(fixture(false).formatPeriodText(1, 1), '第 1-2 节')
})

test('clock self-study uses its real time while ordinary period one keeps its meaning', () => {
  const format = fixture(true).formatPeriodText
  assert.equal(format(1, 1, { time_basis: 'CLOCK', time_label: '07:30—07:50' }), '07:30—07:50')
  assert.equal(format(1, 1, { time_snapshot: { time_basis: 'CLOCK', time_label: '18:50—20:25' } }), '18:50—20:25')
  assert.equal(format(1, 1, { time_basis: 'PERIODS', time_label: '08:10—08:55' }), '第 1 节')
})
