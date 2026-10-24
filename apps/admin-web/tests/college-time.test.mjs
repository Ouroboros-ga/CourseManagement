import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => {
    if (!(name in imports)) throw new Error(`Unexpected import ${name}`)
    return imports[name]
  } })
  return module.exports
}

function fixture() {
  const collegeId = vue.shallowRef('A'), callbacks = [], previews = [], publishes = []
  const session = vue.reactive({ currentUser: { id: 'user-1' } })
  const api = {
    listCollegeTimeVersions: async () => [],
    previewCollegeTime: (...args) => new Promise(resolve => previews.push({ args, resolve })),
    publishCollegeTime: async (...args) => {
      publishes.push(args)
      return { revision: args[3], next_version: 2, retained_future_task_ids: [], existing_tasks_keep_snapshot: true, id: '41', version: 2 }
    }
  }
  const { useCollegeTimeConfiguration } = load('../src/composables/useCollegeTimeConfiguration.ts', {
    vue: { ...vue, onUnmounted: callback => callbacks.push(callback) },
    '../api/collegeTime': api,
    '../stores/session': { useSessionStore: () => session },
    '../utils/contextEpoch': load('../src/utils/contextEpoch.ts')
  })
  const scope = vue.effectScope()
  const state = scope.run(() => useCollegeTimeConfiguration(() => collegeId.value))
  return { collegeId, session, state, previews, publishes, stop: () => { callbacks.forEach(callback => callback()); scope.stop() } }
}
const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }
const configure = state => {
  state.semesterId.value = 'semester-1'
  state.form.value = { ...state.form.value, effective_from: '2026-09-01' }
}
const response = revision => ({ revision, next_version: 2, retained_future_task_ids: [], existing_tasks_keep_snapshot: true })

test('college or semester context changes discard late previews', async () => {
  const f = fixture()
  try {
    configure(f.state); await flush()
    const first = f.state.preview()
    f.collegeId.value = 'B'; await flush()
    f.previews[0].resolve(response('old-college'))
    await first
    assert.equal(f.state.previewResult.value, null)

    f.state.semesterId.value = 'semester-1'
    f.state.form.value = { ...f.state.form.value, effective_from: '2026-09-01' }
    await flush()
    const second = f.state.preview()
    f.state.semesterId.value = 'semester-2'; await flush()
    f.previews[1].resolve(response('old-semester'))
    await second
    assert.equal(f.state.previewResult.value, null)
  } finally { f.stop() }
})

test('form edits while preview is pending discard the response and old preview cannot publish', async () => {
  const f = fixture()
  try {
    configure(f.state); await flush()
    const pending = f.state.preview()
    f.state.form.value = { ...f.state.form.value, effective_from: '2026-09-08' }
    await flush()
    f.previews[0].resolve(response('stale-revision'))
    await pending
    assert.equal(f.state.previewResult.value, null)
    await f.state.publish()
    assert.equal(f.publishes.length, 0)
  } finally { f.stop() }
})

test('publish sends the exact preview revision and configuration', async () => {
  const f = fixture()
  try {
    configure(f.state); await flush()
    const pending = f.state.preview()
    f.previews[0].resolve(response('a'.repeat(64)))
    await pending
    await f.state.publish()
    assert.equal(f.publishes.length, 1)
    assert.equal(f.publishes[0][3], 'a'.repeat(64))
    assert.equal(f.publishes[0][2].effective_from, '2026-09-01')
    assert.equal(f.publishes[0][2].periods[0].start_time, '08:00')
    assert.equal(f.state.previewResult.value, null)
    await f.state.publish()
    assert.equal(f.publishes.length, 1)
  } finally { f.stop() }
})

test('account, college, and semester changes reset the form and require a new effective date', async () => {
  const f = fixture()
  try {
    configure(f.state)
    f.state.form.value = { ...f.state.form.value, confirm_existing_tasks: true }
    await flush()

    f.collegeId.value = 'B'
    await flush()
    assert.equal(f.state.form.value.effective_from, '')
    assert.equal(f.state.form.value.confirm_existing_tasks, false)
    await f.state.preview()
    assert.equal(f.previews.length, 0)
    f.state.form.value = { ...f.state.form.value, effective_from: '2026-09-08' }
    await flush()
    const afterCollegeChange = f.state.preview()
    f.previews[0].resolve(response('new-college-revision'))
    await afterCollegeChange

    f.state.form.value = { ...f.state.form.value, effective_from: '2026-09-15', confirm_existing_tasks: true }
    f.state.semesterId.value = 'semester-2'
    await flush()
    assert.equal(f.state.form.value.effective_from, '')
    assert.equal(f.state.form.value.confirm_existing_tasks, false)

    f.state.form.value = { ...f.state.form.value, effective_from: '2026-09-22', confirm_existing_tasks: true }
    f.session.currentUser.id = 'user-2'
    await flush()
    assert.equal(f.state.form.value.effective_from, '')
    assert.equal(f.state.form.value.confirm_existing_tasks, false)
  } finally { f.stop() }
})

test('the explicit publish action acknowledges previewed future tasks without a second checkbox', async () => {
  const f = fixture()
  try {
    configure(f.state); await flush()
    const pending = f.state.preview()
    f.previews[0].resolve({ ...response('revision-with-tasks'), retained_future_task_ids: ['9007199254740993123'] })
    await pending
    await f.state.publish()
    assert.equal(f.publishes.length, 1)
    assert.equal(f.publishes[0][2].confirm_existing_tasks, true)
    assert.equal(f.publishes[0][2].effective_from, '2026-09-01')
    assert.equal(f.publishes[0][3], 'revision-with-tasks')
  } finally { f.stop() }
})
