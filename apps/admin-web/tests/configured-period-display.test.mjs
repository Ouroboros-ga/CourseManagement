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
