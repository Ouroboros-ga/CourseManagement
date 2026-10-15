import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'

function component(path, props, session, api) {
  const { descriptor } = parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
  const script = compileScript(descriptor, { id: path })
  const code = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const hooks = [], mounts = [], module = { exports: {} }
  class Epoch {
    revision = 0
    constructor(key) { this.key = key }
    begin() { const key = this.key(), revision = ++this.revision; return { isCurrent: () => key === this.key() && revision === this.revision } }
    invalidate() { this.revision++ }
  }
  vm.runInNewContext(code, {
    module, exports: module.exports, console,
    require: name => {
      if (name === 'vue') return { ...vue, onMounted: fn => mounts.push(fn), onUnmounted: fn => hooks.push(fn) }
      if (name.endsWith('/stores/session')) return { useSessionStore: () => session }
      if (name.endsWith('/api/academic')) return api
      if (name.endsWith('/api/campus')) return { listGroups: api.listGroups }
      if (name.endsWith('/utils/contextEpoch')) return { ContextEpoch: Epoch }
      if (name.endsWith('/api/workspaceHttp')) return { isAcademicScoped: () => true }
      if (name === 'element-plus') return { ElMessage: { error() {}, success() {}, warning() {} }, ElMessageBox: {} }
      return {}
    }
  })
  const scope = vue.effectScope()
  const state = scope.run(() => module.exports.default.setup(props, { expose() {} }))
  return { state, mounts, stop() { hooks.forEach(fn => fn()); scope.stop() } }
}
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)); await vue.nextTick() }
function fixture(mode, overrides = {}) {
  const calls = []
  const session = vue.reactive({ currentSemesterId: '', currentSemesterName: '', currentUser: { id: 'U1' }, workspaceCollegeId: 'C1', hasPermission: () => false })
  const api = {
    listAdministrativeClasses: async () => ({ items: [] }),
    listStudents: async params => { calls.push(['students', params]); return { items: [{ id: '1', name: '学生甲' }], total: 1 } },
    listVolunteerQualifications: async id => { calls.push(['qualifications', id]); return { items: [] } },
    ...overrides
  }
  return { session, calls, ...component('../src/components/students/StudentDirectory.vue', { mode }, session, api) }
}

test('current student directory loads with no semester and never fetches semester qualifications', async () => {
  const f = fixture('students')
  try {
    await f.state.loadData()
    assert.equal(f.state.students.value.length, 1)
    assert.equal(f.calls[0][1].semester_id, undefined)
    f.session.currentSemesterId = 'S2'; await flush()
    assert.equal(f.calls.length, 1)
    assert.equal(f.state.newStudentForm.value.set_as_volunteer, false)
    assert.equal(f.state.addMode.value, 'new')
  } finally { f.stop() }
})

test('semester qualification view waits for explicit semester and uses that exact semester', async () => {
  const f = fixture('qualifications')
  try {
    await f.state.loadData()
    assert.equal(f.calls.length, 0)
    f.session.hasPermission = code => code === 'volunteer.read'
    f.session.currentSemesterId = 'S2'; await flush()
    assert.equal(f.calls.find(row => row[0] === 'students')[1].semester_id, 'S2')
    assert.equal(f.calls.find(row => row[0] === 'qualifications')[1], 'S2')
  } finally { f.stop() }
})

test('an old student search cannot overwrite the later result', async () => {
  const pending = []
  const f = fixture('students', { listStudents: () => new Promise(resolve => pending.push(resolve)) })
  try {
    const first = f.state.loadData(); await flush()
    f.state.searchQuery.value = 'new'
    const second = f.state.loadData(); await flush()
    pending[1]({ items: [{ id: '2' }], total: 1 }); await second
    pending[0]({ items: [{ id: '1' }], total: 1 }); await first
    assert.equal(f.state.students.value[0].id, '2')
  } finally { f.stop() }
})

test('group operations follows the global semester instead of choosing the first active semester', async () => {
  const session = vue.reactive({ currentSemesterId: 'S2', currentSemesterName: '第二学期' })
  const f = component('../src/components/campus/GroupOperations.vue', { collegeId: 'C1', groups: [], capabilities: [], isSuper: false, mode: 'members' }, session, {})
  try {
    assert.equal(f.state.semesterId.value, 'S2')
    session.currentSemesterId = 'S3'; await flush()
    assert.equal(f.state.semesterId.value, 'S3')
  } finally { f.stop() }
})

test('academic timetable reuses academic reads without requesting inspection groups', async () => {
  const calls = []
  const session = vue.reactive({ currentSemesterId: 'S2', currentUser: { id: 'U1' }, workspaceCollegeId: 'C1', campusRuntime: { scheduling: true }, hasPermission: code => code === 'academic.read' })
  const f = component('../src/components/academic/TeachingSchedule.vue', { mode: 'academic', openImport: false }, session, {
    listGroups: async () => { calls.push('groups'); return [] },
    listAdministrativeClasses: async () => ({ items: [] }),
    getMasterTimetable: async params => { calls.push(['master', params.semester_id]); return { items: [] } }
  })
  try {
    for (const mount of f.mounts) await mount()
    assert.equal(calls.includes('groups'), false)
    assert.equal(calls.find(row => Array.isArray(row))[1], 'S2')
  } finally { f.stop() }
})
