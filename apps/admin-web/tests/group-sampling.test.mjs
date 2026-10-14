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

const bigClassId = '9007199254740993123'
const bigTaskId = '9007199254740993987'
const classItem = (id, name = `行政班${id}`) => ({ id, class_name: name, class_code: `C-${id}`, status: 'ACTIVE' })
const sampleItem = (id = 'course:2026-09-01') => ({
  task_key: id, inspection_date: '2026-09-01', week_no: 1, start_period: 1, end_period: 2,
  class_name_snapshot: '高一一班', course_name_snapshot: '数学', classroom_snapshot: 'A101', expected_count: 42
})
const previewResponse = (revision = 'r'.repeat(64)) => ({ selection_revision: revision, candidate_count: 3, selected_count: 1, counts: { [bigClassId]: 1 }, items: [sampleItem()] })
const generateResponse = (ids = [bigTaskId]) => ({
  created: 1, existed: 0, total_planned: 1, assignable_task_ids: ids,
  tasks: ids.map(task_id => ({ task_id, created: true, status: '待执行', assignment_id: null }))
})
const assignmentResponse = () => ({ assigned_count: 0, unassigned_count: 1, target_task_count: 1, assigned: [], unassigned: [{ task_id: bigTaskId, reason_code: 'NO_QUALIFICATION', message: '没有有效资格' }] })

function fixture(initial = { college: 'C1', group: 'G1', semester: 'S1', canGenerate: true, canAssign: true }) {
  const values = Object.fromEntries(Object.entries(initial).map(([key, value]) => [key, vue.shallowRef(value)]))
  const callbacks = [], calls = [], previews = [], generates = [], assignments = []
  let assignFailures = 0
  const api = {
    listClassPage: async (...args) => {
      calls.push(['classes', ...args])
      const items = args[2] === 1
        ? Array.from({ length: 100 }, (_unused, index) => index === 0
          ? classItem(bigClassId, '高一一班')
          : classItem(String(100000 + index)))
        : [classItem('100100', '高二一班')]
      return { items, total: 101, page: args[2], page_size: args[1] }
    },
    preview: (...args) => new Promise((resolve, reject) => { calls.push(['preview', ...args]); previews.push({ args, resolve, reject }) }),
    generate: async (...args) => { calls.push(['generate', ...args]); generates.push(args); return generateResponse() },
    assign: async (...args) => {
      calls.push(['assign', ...args]); assignments.push(args)
      if (assignFailures-- > 0) throw new Error('排班服务暂不可用')
      return assignmentResponse()
    }
  }
  const { useGroupSampling } = load('../src/composables/useGroupSampling.ts', {
    vue: { ...vue, onUnmounted: callback => callbacks.push(callback) },
    '../api/groupSampling': { groupSamplingApi: api }
  })
  const ids = ['draw-one', 'draw-two', 'draw-three']
  const state = vue.effectScope().run(() => useGroupSampling({
    collegeId: () => values.college.value,
    groupId: () => values.group.value,
    semesterId: () => values.semester.value,
    canGenerate: () => values.canGenerate.value,
    canAssign: () => values.canAssign.value
  }, api, () => ids.shift() || 'draw-last'))
  return {
    values, state, calls, previews, generates, assignments,
    failNextAssign: () => { assignFailures = 1 },
    stop: () => callbacks.forEach(callback => callback())
  }
}

const flush = async () => { await vue.nextTick(); await Promise.resolve(); await vue.nextTick() }
const configure = state => {
  state.setDateRange('2026-09-01', '2026-09-07')
  state.toggleClass(bigClassId, true)
  state.setCount(bigClassId, 2)
  state.setRequirePhoto(true)
}
const completePreview = async (f, revision) => {
  const pending = f.state.preview()
  f.previews.at(-1).resolve(previewResponse(revision))
  await pending
}

test('empty context makes no calls; class picker reads every 100-row page', async () => {
  const empty = fixture({ college: '', group: 'G1', semester: 'S1', canGenerate: true, canAssign: true })
  try {
    await flush()
    assert.equal(empty.calls.length, 0)
  } finally { empty.stop() }

  const f = fixture()
  try {
    await flush()
    assert.equal(f.calls.filter(call => call[0] === 'classes').length, 2)
    assert.deepEqual(f.calls.filter(call => call[0] === 'classes').map(call => call.slice(1)), [
      ['C1', 100, 1], ['C1', 100, 2]
    ])
  } finally { f.stop() }
})

test('college and semester switches discard late previews and reset all flow state', async () => {
  const f = fixture()
  try {
    await flush(); configure(f.state); await flush()
    const pending = f.state.preview()
    f.values.college.value = 'C2'; await flush()
    f.previews[0].resolve(previewResponse('old-college'))
    await pending
    assert.equal(f.state.previewResult.value, null)
    assert.equal(f.state.form.value.selectedClassIds.length, 0)
    assert.deepEqual(f.state.generateResult.value, null)

    configure(f.state); await flush()
    const second = f.state.preview()
    f.values.semester.value = 'S2'; await flush()
    f.previews[1].resolve(previewResponse('old-semester'))
    await second
    assert.equal(f.state.previewResult.value, null)
    assert.deepEqual(f.state.assignmentResult.value, null)
  } finally { f.stop() }
})

test('form changes invalidate preview revision and a late result cannot be used to generate', async () => {
  const f = fixture()
  try {
    await flush(); configure(f.state); await flush()
    const pending = f.state.preview()
    f.state.setCount(bigClassId, 3)
    f.previews[0].resolve(previewResponse())
    await pending
    assert.equal(f.state.previewResult.value, null)
    await f.state.generate()
    assert.equal(f.generates.length, 0)
  } finally { f.stop() }
})

test('preview and generation reuse the same frozen body and revision; generation is single-use', async () => {
  const f = fixture()
  try {
    await flush(); configure(f.state); await flush()
    const previewing = f.state.preview()
    const exactPreviewBody = structuredClone(f.previews[0].args[2])
    f.previews[0].resolve(previewResponse('selection-r1'))
    await previewing
    f.state.setCount(bigClassId, 4)
    await flush()
    assert.equal(f.state.previewResult.value, null)
    await f.state.generate()
    assert.equal(f.generates.length, 0)

    f.state.setCount(bigClassId, 2)
    await completePreview(f, 'selection-r2')
    const previewBody = f.previews.at(-1).args[2]
    assert.equal(previewBody.draw_id, 'draw-two')
    await f.state.generate()
    assert.equal(f.generates.length, 1)
    assert.equal(JSON.stringify(f.generates[0][2]), JSON.stringify({ ...previewBody, selection_revision: 'selection-r2' }))
    assert.equal(f.generates[0][2].semester_id, 'S1')
    assert.equal(f.generates[0][2].counts[bigClassId], 2)
    assert.equal(f.generates[0][2].date_from, '2026-09-01')
    assert.equal(f.generates[0][2].require_photo, true)
    assert.equal(exactPreviewBody.counts[bigClassId], 2)
    await f.state.generate()
    assert.equal(f.generates.length, 1)
    assert.equal(f.state.generateResult.value.assignable_task_ids[0], bigTaskId)
  } finally { f.stop() }
})

test('assign failure retains generated facts and retry sends the exact BIGINT task ID set', async () => {
  const f = fixture()
  try {
    await flush(); configure(f.state); await flush()
    await completePreview(f, 'selection-r3')
    await f.state.generate()
    const savedGeneration = structuredClone(f.state.generateResult.value)
    f.failNextAssign()
    await f.state.assign()
    assert.equal(JSON.stringify(f.state.generateResult.value), JSON.stringify(savedGeneration))
    assert.match(f.state.error.value, /暂不可用/)
    await f.state.assign()
    assert.equal(f.assignments.length, 2)
    for (const call of f.assignments) {
      assert.equal(call[2].semester_id, 'S1')
      assert.equal(JSON.stringify(call[2].task_ids), JSON.stringify([bigTaskId]))
      assert.equal(typeof call[2].task_ids[0], 'string')
    }
    assert.equal(f.state.assignmentResult.value.unassigned[0].task_id, bigTaskId)
  } finally { f.stop() }
})

test('empty assignable IDs never call assign; permissions and context changes clear writes', async () => {
  const f = fixture()
  try {
    await flush(); configure(f.state); await flush(); await completePreview(f, 'selection-r4')
    f.state.generateResult.value = generateResponse([])
    await f.state.assign()
    assert.equal(f.assignments.length, 0)
    f.values.canAssign.value = false; await flush()
    assert.equal(f.state.generateResult.value, null)
    f.state.generateResult.value = generateResponse()
    await f.state.assign()
    assert.equal(f.assignments.length, 0)
  } finally { f.stop() }
})

test('API methods use exact endpoints and preserve string IDs in JSON bodies', async () => {
  const requests = []
  const api = load('../src/api/groupSampling.ts', { './http': { request: async (...args) => { requests.push(args); return {} } } }).groupSamplingApi
  const body = { semester_id: '800000000000000001', date_from: '2026-09-01', date_to: '2026-09-02', counts: { [bigClassId]: 1 }, draw_id: 'abc', require_photo: true }
  await api.listClassPage('C/1', 100, 2)
  await api.preview('C/1', 'G 2', body)
  await api.generate('C/1', 'G 2', { ...body, selection_revision: 'x'.repeat(64) })
  await api.assign('C/1', 'G 2', { semester_id: body.semester_id, task_ids: [bigTaskId] })
  assert.match(requests[0][0], /C%2F1\/academic\/administrative-classes\?page_size=100&page=2/)
  assert.match(requests[1][0], /C%2F1\/groups\/G%202\/inspection\/sample-preview$/)
  assert.match(requests[2][0], /\/generate$/)
  assert.match(requests[3][0], /\/assign$/)
  assert.equal(JSON.parse(requests[2][1].body).counts[bigClassId], 1)
  assert.equal(JSON.parse(requests[3][1].body).task_ids[0], bigTaskId)
})
