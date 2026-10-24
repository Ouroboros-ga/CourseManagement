import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], Error, Date, Set, JSON, crypto: { randomUUID: () => 'group-key' }, setTimeout, clearTimeout })
  return module.exports
}
const validAgentId = v => typeof v === 'string' && /^[1-9][0-9]*$/.test(v)
const contract = load('../src/api/assistantWorkspaces.ts', { './http': {}, './importer': {}, './assistantReports': { validAgentId } })
const epoch = load('../src/utils/contextEpoch.ts')
const source = preview => ({ workspace_id: '3', college_id: '1', semester_id: '2', filename: '资料.csv', state: preview?.status === 'QUEUED' ? 'PREVIEW_QUEUED' : 'READY', business_data_applied: false, error_code: null, preview, inspection: { protocol_version: 1, business_data_applied: false, source_sha256: 'a'.repeat(64), files: [{ member_no: 1, filename: '资料.csv', target: 'volunteer', blocked: false, message: '', archive_member: null, sha256: 'a'.repeat(64), size_bytes: 3, duplicate_of: null }] } })
const receipt = (extra = {}) => ({ request_key: 'group-key', target: 'volunteer', member_nos: [1], teaching_class_id: null, course_type_id: null, status: 'QUEUED', batch_ids: [], error_code: null, ...extra })
const flush = async () => { await vue.nextTick(); await new Promise(r => setImmediate(r)) }
function fixture(extra = {}) {
  const calls = [], opened = []
  const api = { read: async () => source(null), prepare: async (id, scope, body) => { calls.push(body); return source(receipt()) }, batch: async id => ({ id, target: 'volunteer', status: 'PREVIEW', semester_id: '2' }), ...extra }
  const { useStoredImportPreview } = load('../src/composables/useStoredImportPreview.ts', { vue, '../api/assistantWorkspaces': { ...contract, assistantWorkspacesApi: api }, '../utils/contextEpoch': epoch })
  const context = vue.reactive({ key: 'user:rev1', collegeId: '1', semesterId: '2', available: true, selection: { workspaceId: '3', memberNos: [1], filenames: ['资料.csv'] }, target: 'volunteer', teachingClassId: '', courseTypeId: '' })
  const scope = vue.effectScope()
  const state = scope.run(() => useStoredImportPreview(() => ({ ...context }), rows => opened.push(rows)))
  return { calls, opened, context, state, stop: () => scope.stop() }
}

test('queued stored group resumes original previews only after durable success, without uploading bytes', async () => {
  let ready = false
  const f = fixture({ read: async () => source(ready ? receipt({ status: 'SUCCEEDED', batch_ids: ['11'] }) : null) })
  try {
    await f.state.prepare(); assert.equal(f.calls.length, 1); assert.equal(f.opened.length, 0)
    ready = true; await f.state.refresh()
    assert.equal(f.opened[0][0].id, '11'); assert.equal(f.opened[0][0].filename, '资料.csv')
  } finally { f.stop() }
})
test('uncertain prepare retains original request key for explicit retry', async () => {
  const calls = []
  const f = fixture({ prepare: async (id, scope, body) => { calls.push(body); if (calls.length === 1) throw new Error('network'); return source(receipt()) } })
  try { await f.state.prepare(); assert.equal(calls.length, 1); await f.state.prepare(); assert.equal(calls[0].request_key, calls[1].request_key) }
  finally { f.stop() }
})
test('scope changes fence late receipts and original batch reads', async () => {
  let resolve
  const f = fixture({ prepare: () => new Promise(r => { resolve = r }) })
  try {
    const work = f.state.prepare(); await flush(); f.context.key = 'other-user'; await flush()
    resolve(source(receipt({ status: 'SUCCEEDED', batch_ids: ['11'] }))); await work
    assert.equal(f.opened.length, 0); assert.equal(f.state.waiting.value, false)
  } finally { f.stop() }
})
test('wrong target or already saved original batch cannot be resumed for a second save', async () => {
  for (const draft of [{ id: '11', target: 'admin_roster', status: 'PREVIEW' }, { id: '11', target: 'volunteer', status: 'APPLIED' }]) {
    const f = fixture({ read: async () => source(receipt({ status: 'SUCCEEDED', batch_ids: ['11'] })), batch: async () => draft })
    try { await f.state.prepare(); assert.equal(f.opened.length, 0); assert.ok(f.state.error.value) }
    finally { f.stop() }
  }
})

test('returning to an earlier completed group reuses its original receipt instead of creating new drafts', async () => {
  const original = receipt({ status: 'SUCCEEDED', batch_ids: ['11'] })
  const f = fixture({ read: async () => ({ ...source(receipt({ target: 'admin_roster', member_nos: [2], status: 'SUCCEEDED', batch_ids: ['12'] })), preview_receipts: [original] }) })
  try { await f.state.prepare(); assert.equal(f.calls.length, 0); assert.equal(f.opened[0][0].id, '11') }
  finally { f.stop() }
})
