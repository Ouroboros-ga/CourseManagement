import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

// Run the component's actual async loader with isolated requests and refs.
const source = readFileSync(new URL('../src/components/academic/TeachingSchedule.vue', import.meta.url), 'utf8')
const loader = source.slice(source.indexOf('async function loadData('), source.indexOf('\nasync function loadMasterTimetableData'))
function setup({ listTasks, queryCourseOccurrences }) {
  const ref = value => ({ value })
  const state = Object.fromEntries(Object.entries({
    occurrencePage: 1, weekTaskPage: 1, selectedKeys: [], selectionRevision: 'old',
    selectionScope: {}, smartSampleResult: null, occurrences: [{ id: 'stale' }],
    weekTasks: [{ id: 'stale' }], occurrenceTotal: 99, weekTaskTotal: 99,
    adminClasses: [{ id: '1' }], selectedAdminClassId: '', executionGroupId: '',
    dispatchCourseTypeId: '', organizationMode: false, loading: false, dispatchError: 'old error'
  }).map(([name, value]) => [name, ref(value)]))
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule('export ' + loader, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText, {
    module, exports: module.exports, ...state, dispatchEpoch: 0, dispatchContext: () => 'current',
    sessionStore: { currentSemesterId: '1', currentWeekNo: 6, hasPermission: () => true,
      weekDateRange: { start: '2026-10-19', end: '2026-10-25' } },
    listTasks, queryCourseOccurrences, Error, console: { error() {} },
    ElMessage: { error() {}, warning() {} }
  })
  return { state, load: module.exports.loadData }
}

test('task failure stays visible and does not prevent independent occurrence loading', async () => {
  const { state, load } = setup({ listTasks: async () => { throw new Error('HTTP 500') },
    queryCourseOccurrences: async () => ({ items: [{ id: 'course' }], total: 1, selection_revision: 'new' }) })
  await load()
  assert.equal(state.occurrences.value[0]?.id, 'course')
  assert.match(state.dispatchError.value, /任务.*HTTP 500/)
  assert.equal(state.weekTasks.value.length, 0)
  assert.equal(state.weekTaskTotal.value, 0)
  assert.equal(state.loading.value, false)
})

test('occurrence failure preserves successful tasks and clears stale totals', async () => {
  const { state, load } = setup({ listTasks: async () => ({ items: [{ id: 'task' }], total: 1 }),
    queryCourseOccurrences: async () => { throw new Error('HTTP 500') } })
  await load()
  assert.equal(state.weekTasks.value[0]?.id, 'task')
  assert.match(state.dispatchError.value, /课次.*HTTP 500/)
  assert.equal(state.occurrences.value.length, 0)
  assert.equal(state.occurrenceTotal.value, 0)
})

test('successful retry removes the error and updates both page totals', async () => {
  const { state, load } = setup({ listTasks: async () => ({ items: [], total: 0 }),
    queryCourseOccurrences: async () => ({ items: [], total: 0, selection_revision: 'new' }) })
  await load()
  assert.equal(state.dispatchError.value, '')
  assert.equal(state.weekTaskTotal.value, 0)
  assert.equal(state.occurrenceTotal.value, 0)
  assert.match(source, /v-if="!loading && !dispatchError && !hasData"/)
})
