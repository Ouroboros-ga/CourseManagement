import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name],
    Error, URLSearchParams, Date, Blob })
  return module.exports
}
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const epoch = load('../src/utils/contextEpoch.ts')
const wire = (overrides = {}) => ({
  kind: 'ATTENDANCE_REPORT_DOWNLOAD', artifact_status: 'NOT_GENERATED', format: 'ANALYTICS_XLSX',
  college_id: '1', window: { semester_id: '2', week_no: 3 }, matching_task_count: 4,
  download: { method: 'GET', requires_login: true, path: '/api/v1/colleges/1/statistics/attendance/export?semester_id=2&week_no=3' }, ...overrides
})
const task = (data = wire()) => ({ task_id: '9', status: 'SUCCEEDED', result: { status: 'SUCCEEDED', data } })

function fixture(overrides = {}) {
  const calls = [], saved = []
  const api = {
    read: async id => { calls.push(['read', id]); return task() },
    download: async plan => { calls.push(['download', plan]); return { blob: new Blob(['report']), filename: '后台文件.xlsx' } },
    ...overrides
  }
  const contracts = load('../src/api/assistantReports.ts', { './http': { request() { throw new Error('unexpected network') } } })
  const { useAssistantReportExport } = load('../src/composables/useAssistantReportExport.ts', {
    vue, '../api/assistantReports': { ...contracts, assistantReportsApi: api }, '../utils/contextEpoch': epoch
  })
  const context = vue.reactive({ key: 'user1:rev1', taskId: '9', collegeId: '1', semesterId: '2', available: true })
  const scope = vue.effectScope()
  const state = scope.run(() => useAssistantReportExport(() => ({ ...context }), value => saved.push(value)))
  return { context, state, calls, saved, stop: () => scope.stop() }
}

test('ready means prepared; only an explicit click fetches and saves the file', async () => {
  const f = fixture()
  try {
    await flush(); assert.equal(f.state.plan.value.format, 'ANALYTICS_XLSX')
    assert.equal(f.saved.length, 0); assert.equal(f.calls.length, 1)
    await f.state.download()
    assert.equal(f.saved[0].filename, '后台文件.xlsx')
    assert.match(f.state.notice.value, /下载/)
  } finally { f.stop() }
})

test('pending, failed and canceled tasks never expose a download action', async () => {
  for (const status of ['QUEUED', 'RUNNING', 'FAILED', 'CANCELED']) {
    const f = fixture({ read: async () => ({ task_id: '9', status, result: null }) })
    try {
      await flush(); await f.state.download()
      assert.equal(f.state.plan.value, null); assert.equal(f.saved.length, 0)
      assert.equal(f.state.taskStatus.value, status)
    } finally { f.stop() }
  }
})

test('forged URLs, mismatched college or semester and extra window selectors are rejected', async () => {
  const bad = [
    wire({ download: { method: 'GET', requires_login: true, path: 'https://untrusted.invalid/report' } }),
    wire({ college_id: '3' }), wire({ window: { semester_id: '4', week_no: 3 } }),
    wire({ window: { semester_id: '2', week_no: 3, student_id: '7' } }),
    wire({ artifact_status: 'GENERATED' }), wire({ format: 'SQL' })
  ]
  for (const data of bad) {
    const f = fixture({ read: async () => task(data) })
    try { await flush(); await f.state.download(); assert.equal(f.state.plan.value, null); assert.equal(f.saved.length, 0); assert.ok(f.state.error.value) }
    finally { f.stop() }
  }
})

test('an unknown or rounded task ID does not issue a request', async () => {
  const f = fixture()
  try {
    await flush(); f.context.taskId = '01'; await flush()
    assert.equal(f.calls.length, 1); assert.equal(f.state.plan.value, null)
    assert.match(f.state.error.value, /编号/)
  } finally { f.stop() }
})

test('late task reads cannot restore a different account or college', async () => {
  let release
  const f = fixture({ read: () => new Promise(resolve => { release = resolve }) })
  try {
    await flush(); f.context.available = false; f.context.key = 'user2'; await flush()
    release(task()); await flush()
    assert.equal(f.state.plan.value, null); assert.equal(f.saved.length, 0)
  } finally { f.stop() }
})

test('account or authorization changes during download discard the blob before saving', async () => {
  let release
  const f = fixture({ download: () => new Promise(resolve => { release = resolve }) })
  try {
    await flush(); const pending = f.state.download()
    f.context.key = 'user1:rev2'; await flush()
    release({ blob: new Blob(['old private report']), filename: 'old.xlsx' }); await pending
    assert.equal(f.saved.length, 0); assert.equal(f.state.notice.value, '')
  } finally { f.stop() }
})

test('download errors clear the old action and require an explicit refresh', async () => {
  const f = fixture({ download: async () => { throw new Error('权限变化') } })
  try {
    await flush(); await f.state.download(); await f.state.download()
    assert.equal(f.calls.filter(x => x[0] === 'read').length, 1)
    assert.equal(f.state.plan.value, null); assert.match(f.state.error.value, /刷新/)
    await f.state.refresh(); assert.ok(f.state.plan.value)
  } finally { f.stop() }
})

test('duplicate download clicks and component disposal do not save twice or after unmount', async () => {
  let release
  const f = fixture({ download: () => new Promise(resolve => { release = resolve }) })
  await flush(); const pending = f.state.download(); await f.state.download()
  assert.equal(f.state.downloading.value, true)
  f.stop(); release({ blob: new Blob(['report']), filename: 'discarded.xlsx' }); await pending
  assert.equal(f.saved.length, 0)
})

test('the API reconstructs one fixed same-origin path and preserves string IDs', async () => {
  const calls = []
  const { assistantReportsApi, parseReportAction } = load('../src/api/assistantReports.ts', {
    './http': { request: async (...args) => { calls.push(args); return { blob: new Blob(['x'], { type: 'application/octet-stream' }), filename: 'report.xlsx' } } }
  })
  const plan = parseReportAction(wire(), '1', '2')
  await assistantReportsApi.download(plan)
  assert.equal(calls[0][0], wire().download.path)
  assert.equal(calls[0][3], 'download')
  assert.equal(JSON.stringify(plan).includes('https://'), false)
})

test('all three report formats use their own fixed route and MIME type', async () => {
  const cases = [
    ['ANALYTICS_XLSX', 'export', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
    ['DETAIL_DOCX', 'export-detail-doc', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    ['STUDY_XLSX', 'export-study-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']
  ]
  for (const [format, suffix, mime] of cases) {
    const calls = []
    const api = load('../src/api/assistantReports.ts', { './http': { request: async (...args) => {
      calls.push(args); return { blob: new Blob(['report'], { type: mime }), filename: null }
    } } })
    const path = `/api/v1/colleges/1/statistics/attendance/${suffix}?semester_id=2&week_no=3`
    const plan = api.parseReportAction(wire({ format, download: { method: 'GET', requires_login: true, path } }), '1', '2')
    const file = await api.assistantReportsApi.download({ ...plan, path: 'https://untrusted.invalid' })
    assert.equal(calls[0][0], path)
    assert.match(file.filename, format === 'DETAIL_DOCX' ? /\.docx$/ : /\.xlsx$/)
  }
})

test('invalid calendar dates, overly broad windows and mixed selectors are rejected', () => {
  const api = load('../src/api/assistantReports.ts')
  for (const window of [
    { semester_id: '2', date_from: '2026-02-30', date_to: '2026-03-01' },
    { semester_id: '2', date_from: '2026-01-01', date_to: '2026-10-01' },
    { semester_id: '2', week_no: 3, date_from: '2026-01-01', date_to: '2026-01-02' }
  ]) assert.throws(() => api.parseReportAction(wire({ window }), '1', '2'))
})

test('large college and semester IDs reach the request without Number conversion', async () => {
  const id = '9007199254740993', calls = []
  const api = load('../src/api/assistantReports.ts', { './http': { request: async (...args) => {
    calls.push(args); return { blob: new Blob(['x'], { type: 'application/octet-stream' }), filename: 'report.xlsx' }
  } } })
  const path = `/api/v1/colleges/${id}/statistics/attendance/export?semester_id=${id}&week_no=3`
  const value = wire({ college_id: id, window: { semester_id: id, week_no: 3 }, download: { method: 'GET', requires_login: true, path } })
  await api.assistantReportsApi.download(api.parseReportAction(value, id, id))
  assert.equal(calls[0][0], path)
})

test('a successful JSON response is never saved as an Excel file', async () => {
  const api = load('../src/api/assistantReports.ts', { './http': { request: async () => ({ blob: new Blob(['{}'], { type: 'application/json' }), filename: 'report.xlsx' }) } })
  await assert.rejects(api.assistantReportsApi.download(api.parseReportAction(wire(), '1', '2')), /文件响应异常/)
})
