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
  vm.runInNewContext(code, { module, exports: module.exports, URLSearchParams, require: name => {
    if (!(name in imports)) throw new Error(`Unexpected import ${name}`)
    return imports[name]
  } })
  return module.exports
}

const row = (id = '9007199254740993123', extra = {}) => ({
  id, student_id: '9007199254740993124', semester_id: '800000000000000001',
  effective_from: '2026-09-01', effective_to: '2027-01-31', status: 'ACTIVE', lock_version: 7, ...extra
})

function fixture(initial = { college: 'C1', group: 'G1', semester: 'S1', canManage: true, isSuper: true }) {
  const values = Object.fromEntries(Object.entries(initial).map(([key, value]) => [key, vue.shallowRef(value)]))
  const callbacks = [], calls = [], pendingImpact = []
  const api = {
    list: async (...args) => { calls.push(['list', ...args]); return [] },
    candidates: async (...args) => { calls.push(['candidates', ...args]); return [{ id: '9007199254740993124', student_no: '001', name: '李同学' }] },
    create: async (...args) => { calls.push(['create', ...args]); return row() },
    impact: (...args) => { calls.push(['impact', ...args]); return new Promise((resolve, reject) => pendingImpact.push({ resolve, reject })) },
    update: async (...args) => { calls.push(['update', ...args]); return row() },
    revoke: async (...args) => { calls.push(['revoke', ...args]); return row({ status: 'INACTIVE' }) }
  }
  const { useGroupMembers } = load('../src/composables/useGroupMembers.ts', {
    vue: { ...vue, onUnmounted: callback => callbacks.push(callback) },
    '../api/groupMembers': { groupMemberApi: api }
  })
  const state = vue.effectScope().run(() => useGroupMembers({
    collegeId: () => values.college.value,
    groupId: () => values.group.value,
    semesterId: () => values.semester.value,
    canManage: () => values.canManage.value,
    isSuper: () => values.isSuper.value
  }, api))
  return { values, state, calls, pendingImpact, api, stop: () => callbacks.forEach(callback => callback()) }
}

const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }
const impact = (ids = []) => ({ lock_version: 13, retained_future_task_ids: ids, existing_assignments_preserved: true })

test('empty context sends no requests; authorized workspace can read its member and support lists', async () => {
  const empty = fixture({ college: '', group: 'G1', semester: 'S1', canManage: true, isSuper: true })
  try {
    await flush()
    assert.equal(empty.calls.length, 0)
    empty.values.college.value = 'C1'; await flush()
    assert.deepEqual(empty.calls.map(call => call[1]), ['members', 'support-authorizations'])
  } finally { empty.stop() }

  const standard = fixture({ college: 'C1', group: 'G1', semester: 'S1', canManage: true, isSuper: false })
  try {
    await flush()
    assert.deepEqual(standard.calls.map(call => call[1]), ['members', 'support-authorizations'])
  } finally { standard.stop() }
})

test('context switches clear state and ignore late list/candidate responses and errors', async () => {
  const f = fixture()
  let finishOldList
  f.api.list = async (kind, cid, gid, sid) => {
    f.calls.push(['list', kind, cid, gid, sid])
    if (gid === 'G1' && kind === 'members') return new Promise(resolve => { finishOldList = resolve })
    return gid === 'G1' ? [] : [row('new-context')]
  }
  f.state.members.value = [row()]
  const oldLoad = f.state.load()
  f.state.editing.value = row()
  f.values.group.value = 'G2'
  await flush()
  finishOldList([row('stale-context')])
  await oldLoad
  assert.deepEqual(f.state.members.value.map(item => item.id), ['new-context'])
  assert.equal(f.state.editing.value, null)
  assert.equal(f.state.candidates.value.length, 0)
  assert.ok(f.calls.some(call => call[0] === 'list' && call[3] === 'G2'))
  f.stop()
})

test('candidate IDs and DATE strings pass through unchanged; standard users cannot create support', async () => {
  const f = fixture()
  try {
    await flush()
    f.state.startCreate()
    f.state.candidateFrom.value = '2026-09-01'; f.state.candidateTo.value = '2027-01-31'
    await f.state.searchCandidates()
    f.state.selectedCandidate.value = f.state.candidates.value[0]
    f.state.draft.value = { ...f.state.draft.value, effective_from: '2026-09-01', effective_to: '2027-01-31' }
    await f.state.create()
    const createCall = f.calls.find(call => call[0] === 'create')
    assert.equal(createCall[4].student_id, '9007199254740993124')
    assert.equal(createCall[4].semester_id, 'S1')
    assert.equal(createCall[4].effective_from, '2026-09-01')
    assert.equal(createCall[4].effective_to, '2027-01-31')
    f.state.setKind('support-authorizations')
    assert.equal(f.state.activeKind.value, 'support-authorizations')
    f.values.isSuper.value = false; await flush()
    assert.equal(f.state.activeKind.value, 'support-authorizations')
    const before = f.calls.filter(call => call[0] === 'create').length
    f.state.startCreate(); await f.state.create()
    assert.equal(f.calls.filter(call => call[0] === 'create').length, before)
  } finally { f.stop() }
})

test('future task impact requires explicit confirmation and uses fresh lock version', async () => {
  const f = fixture()
  try {
    await flush()
    f.state.startEdit(row())
    f.state.draft.value = { ...f.state.draft.value, effective_from: '2026-09-02', effective_to: '2027-02-01' }
    const checking = f.state.prepareChange(row())
    f.pendingImpact[0].resolve(impact(['9007199254740993999']))
    await checking
    await f.state.applyChange()
    assert.equal(f.calls.some(call => call[0] === 'update'), false)
    f.state.confirmFutureAssignments.value = true
    await f.state.applyChange()
    const update = f.calls.find(call => call[0] === 'update')
    assert.equal(update[4], '9007199254740993123')
    assert.equal(update[5].lock_version, 13)
    assert.equal(update[5].confirm_future_assignments, true)
    assert.equal(update[5].effective_from, '2026-09-02')
    assert.equal(update[5].effective_to, '2027-02-01')
  } finally { f.stop() }
})

test('409 clears stale edit and candidate choices; permission changes invalidate writes', async () => {
  const f = fixture()
  try {
    await flush()
    f.state.startEdit(row())
    const pending = f.state.prepareChange(row())
    f.pendingImpact[0].reject(Object.assign(new Error('conflict'), { status: 409 }))
    await pending
    assert.equal(f.state.editing.value, null)
    assert.equal(f.state.selectedCandidate.value, null)
    assert.match(f.state.error.value, /刷新/)
    f.values.canManage.value = false; await flush()
    f.state.startCreate(); await f.state.create()
    assert.equal(f.calls.some(call => call[0] === 'create'), false)
  } finally { f.stop() }
})

test('an in-flight impact request keeps its original group and cannot populate the new context', async () => {
  const f = fixture()
  try {
    await flush()
    f.state.startEdit(row())
    const pending = f.state.prepareChange(row())
    f.values.group.value = 'G2'; await flush()
    assert.equal(f.state.writing.value, false)
    f.pendingImpact[0].resolve(impact())
    await pending
    const impactCall = f.calls.find(call => call[0] === 'impact')
    assert.equal(impactCall[3], 'G1')
    assert.equal(f.state.pendingChange.value, null)
    assert.equal(f.state.writing.value, false)
  } finally { f.stop() }
})

test('API paths encode path identifiers and query IDs without numeric conversion', async () => {
  const requests = []
  const api = load('../src/api/groupMembers.ts', { './http': { request: async (...args) => { requests.push(args); return [] } } }).groupMemberApi
  await api.list('members', 'C/1', 'G 2', '9007199254740993123')
  await api.candidates('C1', 'G1', '9007199254740993123', '2026-09-01', '2027-01-31', '李', false)
  assert.match(requests[0][0], /C%2F1\/groups\/G%202\/members\?semester_id=9007199254740993123/)
  assert.match(requests[1][0], /semester_id=9007199254740993123/)
  assert.equal(requests[1][0].includes('school=true'), false)
})
