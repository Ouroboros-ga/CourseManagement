import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
const module = { exports: {} }
const source = readFileSync(new URL('../src/utils/groupRules.ts', import.meta.url), 'utf8')
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { module, exports: module.exports })
const { sameGroupRules } = module.exports
const rules = { course_type_ids: ['2', '1'], default_effect: 'BLOCK', type_overrides: {}, own_class_effect: 'BLOCK' }
test('selection order and absent optional defaults do not imply a rule change', () => {
  assert.equal(sameGroupRules(rules, { ...rules, course_type_ids: ['1', '2'], class_mode: 'ALL_AUTHORIZED', class_ids: [], teaching_class_overrides: {} }), true)
})
test('real rule changes and clearing historical exceptions require confirmation', () => {
  assert.equal(sameGroupRules(rules, { ...rules, default_effect: 'ALLOW' }), false)
  assert.equal(sameGroupRules({ ...rules, type_overrides: { 2: 'ALLOW' } }, rules), false)
  assert.equal(sameGroupRules(null, rules), false)
})
