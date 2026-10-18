import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function setup(api) {
  const session = vue.reactive({ currentUser: { id: '1' }, workspaceCollegeId: '1', currentSemesterId: '2', workspace: { authorization_revision: 1 } })
  const module = { exports: {} }
  const source = readFileSync(new URL('../src/composables/useImportIntake.ts', import.meta.url), 'utf8')
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { module, exports: module.exports, require: name => ({ vue: { ...vue, onUnmounted: () => {} }, '../stores/session': { useSessionStore: () => session }, '../api/importer': api })[name] })
  const scope = vue.effectScope(), state = scope.run(() => module.exports.useImportIntake())
  return { session, scope, state }
}

test('mixed files group in business order and only saved files become completed', async () => {
  const { state, scope } = setup({ inspectImportUpload: async (_cid, file) => ({ files: [{ filename: file.name, target: file.name.startsWith('t') ? 'timetable' : 'faculty_staff', blocked: false, archive_member: null, message: '' }] }) })
  try {
    await state.addFiles([{ name: 't.xlsx', size: 100 }, { name: 's.xlsx', size: 100 }])
    assert.deepEqual(Array.from(state.groups.value, g => g.target), ['faculty_staff', 'timetable'])
    state.markSaved('faculty_staff', { files: [{ id: '10', filename: 's.xlsx', summary: {} }] })
    assert.equal(state.entries.value.find(e => e.filename === 's.xlsx').saved, true)
    assert.equal(state.entries.value.find(e => e.filename === 't.xlsx').saved, false)
    assert.equal(state.receipts.value.length, 1)
    // Later parsing failure leaves the successful first group intact.
    await state.addFiles([{ name: 'bad.xlsx', size: 11 * 1024 * 1024 }])
    assert.equal(state.receipts.value.length, 1)
    assert.equal(state.entries.value.filter(e => e.blocked).length, 1)
  } finally { scope.stop() }
})

test('ZIP is reused with only the explicitly selected group members', async () => {
  const { state, scope } = setup({ inspectImportUpload: async () => ({ files: [
    { filename: 'teacher.xlsx', target: 'faculty_staff', archive_member: 'teacher.xlsx', blocked: false },
    { filename: 'class.xlsx', target: 'admin_roster', archive_member: 'class.xlsx', blocked: false }
  ] }) })
  try {
    await state.addFiles([{ name: 'all.zip', size: 100 }])
    const source = state.sources('faculty_staff')[0]
    assert.equal(source.file.name, 'all.zip')
    assert.deepEqual(Array.from(source.members), ['teacher.xlsx'])
  } finally { scope.stop() }
})

test('college change discards late inspection and existing receipts', async () => {
  let resolve
  const { state, session, scope } = setup({ inspectImportUpload: () => new Promise(r => { resolve = r }) })
  try {
    const pending = state.addFiles([{ name: 'a.xlsx', size: 100 }])
    session.workspaceCollegeId = '3'; await vue.nextTick()
    resolve({ files: [{ filename: 'a.xlsx', target: 'faculty_staff', blocked: false }] })
    await pending
    assert.equal(state.entries.value.length, 0)
    assert.equal(state.receipts.value.length, 0)
  } finally { scope.stop() }
})
