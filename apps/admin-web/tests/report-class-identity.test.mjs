import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

test('report drilldown matches frozen class IDs and never guesses by same name', () => {
  const module = { exports: {} }
  const source = readFileSync(new URL('../src/utils/reportClassIdentity.ts', import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports })
  const { detailBelongsToClass, taskBelongsToClass } = module.exports
  const row = { class_id: '10', college_id: '1', class_name: '同名班' }
  assert.equal(detailBelongsToClass(row, { administrative_class_id_snapshot: '20', class_name_snapshot: '同名班' }), false)
  assert.equal(detailBelongsToClass(row, { administrative_class_id_snapshot: '10', class_name_snapshot: '旧名称' }), true)
  assert.equal(taskBelongsToClass(row, { administrative_class_ids: ['20'], class_name_snapshot: '同名班' }), false)
  assert.equal(taskBelongsToClass(row, { administrative_class_ids: ['10'], class_name_snapshot: '旧名称' }), true)
  assert.equal(detailBelongsToClass({ college_id: '1', class_name: '同名班' }, { college_id_snapshot: '2', class_name_snapshot: '同名班' }), false)
})
