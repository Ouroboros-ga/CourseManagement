import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

function setup(confirm) {
  const module = { exports: {} }, calls = [], session = { currentUser: { id: 'operator' } }
  const source = readFileSync(new URL('../src/composables/useResourceDeletion.ts', import.meta.url), 'utf8')
  const request = async (url, options) => {
    calls.push({ url, options })
    return { revision: 'a'.repeat(64), mode: 'RETAIN_HISTORY', can_delete: true, blocking_task_ids: [] }
  }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { module, exports: module.exports, Error, require: name => ({
      'element-plus': { ElMessageBox: { confirm: () => confirm(session) } },
      '../api/http': { request }, '../stores/session': { useSessionStore: () => session }
    })[name] })
  return { remove: module.exports.deleteManagedResource, calls }
}

test('deletion sends the reviewed revision and keeps BIGINT IDs intact', async () => {
  const { remove, calls } = setup(async () => {})
  await remove('9223372036854775806', 'groups', { id: '9223372036854775805', name: 'Group', lock_version: 7 }, () => true)
  assert.equal(calls[1].url, '/api/v1/colleges/9223372036854775806/groups/9223372036854775805')
  assert.deepEqual(JSON.parse(calls[1].options.body), { lock_version: 7, deletion_revision: 'a'.repeat(64) })
})

test('identity switch during confirmation prevents a delete request', async () => {
  const { remove, calls } = setup(async session => { session.currentUser = { id: 'other' } })
  await assert.rejects(remove('1', 'groups', { id: '2', name: 'Group', lock_version: 1 }, () => true), /身份或工作区/)
  assert.equal(calls.length, 1)
})

test('workspace switch during confirmation prevents a delete request', async () => {
  let current = true
  const { remove, calls } = setup(async () => { current = false })
  await assert.rejects(remove('1', 'course-types', { id: '2', name: 'Type', lock_version: 1 }, () => current), /身份或工作区/)
  assert.equal(calls.length, 1)
})
