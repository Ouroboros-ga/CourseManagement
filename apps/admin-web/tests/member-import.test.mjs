import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function setup(api) {
  const module = { exports: {} }
  const source = readFileSync(new URL('../src/composables/useMemberImport.ts', import.meta.url), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { module, exports: module.exports, Error, JSON, require: name => ({ vue, '../api/groupMembers': { memberImportApi: api } })[name] })
  const context = vue.reactive({ collegeId: '1', groupId: '2', semesterId: '3', userId: 'u', allowed: true })
  const scope = vue.effectScope(), state = scope.run(() => module.exports.useMemberImport(() => ({ ...context })))
  state.select({ name: 'members.xlsx' })
  return { context, state, scope }
}
const body = { semester_id: '3', effective_from: '2026-10-19', effective_to: '2027-02-01', enable_qualification: true }
const reviewed = { revision: 'a'.repeat(64), can_commit: true, items: [], count: 1 }

test('late workbook preview is discarded after changing group', async () => {
  let resolve
  const { context, state, scope } = setup({ preview: () => new Promise(r => { resolve = r }) })
  try {
    const run = state.run(body)
    context.groupId = 'other'; await vue.nextTick(); resolve(reviewed); await run
    assert.equal(state.preview.value, null)
  } finally { scope.stop() }
})

test('changing dates cannot submit a preview made for different dates', async () => {
  let writes = 0
  const { state, scope } = setup({ preview: async () => reviewed, commit: async () => { writes++; return { created: 1 } } })
  try {
    await state.run(body)
    assert.equal(await state.run({ ...body, effective_from: '2026-10-20' }, true), false)
    assert.equal(writes, 0)
  } finally { scope.stop() }
})

test('a blocked workbook preview cannot be committed', async () => {
  let writes = 0
  const { state, scope } = setup({ preview: async () => ({ ...reviewed, can_commit: false }), commit: async () => { writes++ } })
  try {
    await state.run(body); await state.run(body, true)
    assert.equal(writes, 0)
  } finally { scope.stop() }
})
