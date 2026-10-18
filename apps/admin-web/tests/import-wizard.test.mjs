import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name] })
  return module.exports
}
const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }

test('changing format keeps the chosen files but changing college clears them', async () => {
  const session = vue.reactive({ currentUser: { id: '1' }, workspaceCollegeId: 'A', currentSemesterId: 'S1', workspace: { authorization_revision: 1 } })
  const cleanup = []
  const { useImportWizard } = load('../src/composables/useImportWizard.ts', {
    vue: { ...vue, onUnmounted: fn => cleanup.push(fn) },
    '../stores/session': { useSessionStore: () => session }, '../api/importer': {}
  })
  const scope = vue.effectScope(), state = scope.run(() => useImportWizard())
  try {
    state.files.value = [{ name: 'a.xls', size: 10 }]; await flush()
    state.target.value = 'grid_timetable'; await flush()
    assert.equal(state.files.value.length, 1, 'teachers should not have to select the folder again')
    session.workspaceCollegeId = 'B'; await flush()
    assert.equal(state.files.value.length, 0)
  } finally { cleanup.forEach(fn => fn()); scope.stop() }
})

test('ZIP members enter the same review and failed members require explicit exclusion before saving', async () => {
  const session = vue.reactive({ currentUser: { id: '1' }, workspaceCollegeId: 'A', currentSemesterId: 'S1', workspace: { authorization_revision: 1 } })
  const confirmations = [], cleanup = [], previews = []
  const { useImportWizard } = load('../src/composables/useImportWizard.ts', {
    vue: { ...vue, onUnmounted: fn => cleanup.push(fn) },
    '../stores/session': { useSessionStore: () => session },
    '../api/importer': {
      previewImportArchive: async () => ({ files: [{ id: '11', filename: 'folder/a.xls' }, { id: '12', filename: 'b.xls' }], errors: [{ filename: 'bad.xls', message: '无法读取' }] }),
      previewImportSet: async (_cid, ids) => { previews.push([...ids]); return { batch_ids: [...ids], revision: 'reviewed', can_confirm: true, files: [] } },
      confirmImportSet: async (...args) => { confirmations.push(args); return { status: 'CONFIRMED', files: [] } }
    }
  })
  const scope = vue.effectScope(), state = scope.run(() => useImportWizard())
  try {
    state.files.value = [{ name: 'batch.ZIP', size: 100 }]; await flush()
    await state.upload(); await state.review()
    assert.equal(state.drafts.value.length, 2)
    assert.equal(state.drafts.value[0].filename, 'folder/a.xls')
    assert.deepEqual(previews[0], ['11', '12'])
    await state.confirm()
    assert.equal(confirmations.length, 0, 'a broken member must not be silently dropped')
    state.excludeUploadFailures()
    await state.confirm()
    assert.equal(confirmations.length, 1)
    assert.deepEqual(Array.from(confirmations[0][1]), ['11', '12'])
  } finally { cleanup.forEach(fn => fn()); scope.stop() }
})

test('folder-relative file names survive upload for a readable review', async () => {
  const session = vue.reactive({ currentUser: { id: '1' }, workspaceCollegeId: 'A', currentSemesterId: 'S1', workspace: { authorization_revision: 1 } })
  const cleanup = []
  const { useImportWizard } = load('../src/composables/useImportWizard.ts', {
    vue: { ...vue, onUnmounted: fn => cleanup.push(fn) },
    '../stores/session': { useSessionStore: () => session },
    '../api/importer': { uploadImportFile: async () => ({ id: '11' }) }
  })
  const scope = vue.effectScope(), state = scope.run(() => useImportWizard())
  try {
    state.files.value = [{ name: 'a.xls', webkitRelativePath: '班级课表/a.xls', size: 100 }]; await flush()
    await state.upload()
    assert.equal(state.drafts.value[0].filename, '班级课表/a.xls')
  } finally { cleanup.forEach(fn => fn()); scope.stop() }
})
test('changing selected files invalidates late preview and confirm submits the exact reviewed set', async () => {
  const session = vue.reactive({ currentUser: { id: '1' }, workspaceCollegeId: 'A', currentSemesterId: 'S1', workspace: { authorization_revision: 1 } })
  const pending = [], confirms = [], cleanup = []
  const { useImportWizard } = load('../src/composables/useImportWizard.ts', {
    vue: { ...vue, onUnmounted: fn => cleanup.push(fn) },
    '../stores/session': { useSessionStore: () => session },
    '../api/importer': { previewImportSet: (...args) => new Promise(resolve => pending.push({ args, resolve })),
      confirmImportSet: async (...args) => { confirms.push(args); return { status: 'CONFIRMED', files: [] } } }
  })
  const scope = vue.effectScope(), state = scope.run(() => useImportWizard())
  try {
    state.selectedIds.value = ['11']; const old = state.review(); await flush()
    state.selectedIds.value = ['22']; await flush()
    pending[0].resolve({ batch_ids: ['11'], revision: 'old', can_confirm: true, files: [] }); await old
    assert.equal(state.plan.value, null)
    const current = state.review(); await flush()
    pending[1].resolve({ batch_ids: ['22'], revision: 'exact-revision', can_confirm: true, files: [] }); await current
    await state.confirm()
    assert.deepEqual(Array.from(confirms[0][1]), ['22'])
    assert.equal(confirms[0][2], 'exact-revision')
    session.workspaceCollegeId = 'B'; await flush()
    assert.equal(state.plan.value, null)
    assert.equal(state.selectedIds.value.length, 0)
  } finally { cleanup.forEach(fn => fn()); scope.stop() }
})
