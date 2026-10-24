import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'

function load(path, imports = {}, globals = {}) {
  const module = { exports: {} }
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  vm.runInNewContext(code, { module, exports: module.exports, require: name => imports[name], Error, Date, Set, Map, JSON, setTimeout, clearTimeout, crypto: { randomUUID: () => 'synthetic-key' }, ...globals })
  return module.exports
}
const validAgentId = value => typeof value === 'string' && /^[1-9][0-9]{0,18}$/.test(value) && BigInt(value) < 2n ** 63n
const requests = []
const contracts = load('../src/api/assistantConversations.ts', {
  './http': { request: async (...args) => { requests.push(args); return {} } }, './assistantReports': { validAgentId }
})
const epoch = load('../src/utils/contextEpoch.ts')
const flush = async () => { await vue.nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const action = (extra = {}) => ({ kind: 'TASK_HANDOFF', task_id: '9', task_status: 'SUCCEEDED', open_path: '/dashboard/reports?assistant_task_id=9', requires_login: true, business_data_applied: false, ...extra })
const turn = (extra = {}) => ({ id: '5', state: 'SUCCEEDED', user_text: '请导出考勤', reply: '<script>合成纯文本</script>', error_code: null, created_at: '2026-10-25T00:00:00Z', actions: [action()], ...extra })
const snapshot = (extra = {}) => ({ id: '3', college_id: '1', semester_id: '2', state: 'OPEN', next_before_turn_id: null, turns: [], ...extra })
const scope = { collegeId: '1', semesterId: '2' }

test('conversation parser preserves plain text and reconstructs only fixed task actions', () => {
  const parsed = contracts.parseConversation(snapshot({ turns: [turn()] }), scope)
  assert.equal(parsed.turns[0].reply, '<script>合成纯文本</script>')
  assert.equal(parsed.turns[0].actions[0].open_path, '/dashboard/reports?assistant_task_id=9')
  assert.equal(contracts.parseConversation(snapshot({ turns: [turn({ actions: [action({ open_path: '/dashboard/academic?tab=imports&assistant_task_id=9' })] })] }), scope).turns[0].actions[0].title, '核对资料')
})

test('wrong scope, malformed IDs, unknown state and arbitrary action paths fail closed', () => {
  for (const data of [snapshot({ college_id: '4' }), snapshot({ semester_id: '4' }), snapshot({ id: 3 }), snapshot({ state: 'READY' }), snapshot({ next_before_turn_id: '01' }), snapshot({ turns: [turn(), turn()] }), snapshot({ turns: [turn({ reply: null })] }), snapshot({ turns: [turn({ actions: [action({ task_id: '01' })] })] }), snapshot({ turns: [turn({ actions: [action({ open_path: 'https://untrusted.invalid' })] })] }), snapshot({ turns: [turn({ actions: [action({ open_path: '/dashboard/reports?assistant_task_id=8' })] })] }), snapshot({ turns: [turn({ actions: [action({ business_data_applied: true })] })] })]) {
    assert.throws(() => contracts.parseConversation(data, scope))
  }
})

test('API requests use login routes and cannot accept model identity fields or bad IDs', async () => {
  requests.length = 0
  await contracts.assistantConversationsApi.send('3', scope, '合成问题', 'one')
  const [path, init] = requests[0]
  assert.equal(path, '/api/v1/assistant/management/conversations/3/messages')
  assert.deepEqual(JSON.parse(init.body), { college_id: '1', semester_id: '2', text: '合成问题', request_key: 'one' })
  assert.throws(() => contracts.assistantConversationsApi.read('01', scope))
})

test('conversation state must be a string rather than a coercible array', () => {
  assert.throws(() => contracts.parseConversation(snapshot({ state: ['OPEN'] }), scope))
})

function fixture(api = {}, stored = null) {
  const calls = [], memory = new Map(stored ? [['management-assistant-conversation', JSON.stringify(stored)]] : [])
  const timers = new Map(); let timerId = 0
  const fakeApi = {
    create: async c => { calls.push(['create', c]); return snapshot() },
    read: async (id, c, before) => { calls.push(['read', id, before]); return snapshot() },
    send: async (id, c, text, key) => { calls.push(['send', text, key]); return snapshot({ submitted_turn_id: '5', turns: [turn({ state: 'QUEUED', reply: null, actions: [] })] }) }, ...api
  }
  const { useManagementConversation } = load('../src/composables/useManagementConversation.ts', {
    vue, '../api/assistantConversations': { ...contracts, assistantConversationsApi: fakeApi }, '../utils/contextEpoch': epoch,
    '../api/assistantReports': { validAgentId }
  }, { setTimeout: fn => { const id = ++timerId; timers.set(id, fn); return id }, clearTimeout: id => timers.delete(id) })
  const context = vue.reactive({ key: 'user1:revision1', ...scope, available: true, active: true })
  const effect = vue.effectScope()
  const state = effect.run(() => useManagementConversation(() => ({ ...context }), {
    storage: { getItem: key => memory.get(key) || null, setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key) }, pollIntervalMs: 60_000
  }))
  return { context, state, calls, memory, timers, poll: async () => { const entry = timers.entries().next().value; if (entry) { timers.delete(entry[0]); entry[1](); await flush() } }, stop: () => effect.stop() }
}

test('first send creates one conversation, queues once and keeps only its pointer in storage', async () => {
  const f = fixture()
  try {
    await flush(); assert.equal(f.calls.length, 0)
    f.state.draft.value = '请导出考勤'; await f.state.send()
    assert.deepEqual(f.calls.map(c => c[0]), ['create', 'send'])
    assert.equal(f.state.turns.value[0].state, 'QUEUED')
    assert.equal(f.state.draft.value, '')
    assert.ok(![...f.memory.values()].join('').includes('请导出考勤'))
    await f.state.send(); assert.equal(f.calls.length, 2)
  } finally { f.stop() }
})

test('refresh restores only the current context pointer without resending a message', async () => {
  const f = fixture({ read: async () => snapshot({ turns: [turn()] }) }, { key: 'user1:revision1', collegeId: '1', semesterId: '2', id: '3' })
  try { await flush(); assert.equal(f.state.turns.value[0].reply, turn().reply); assert.equal(f.state.conversation.value.id, '3') }
  finally { f.stop() }
})

test('network loss keeps the original request key for explicit retry, never auto resends', async () => {
  const attempts = []
  const f = fixture({ send: async (id, c, text, key) => { attempts.push([text, key]); if (attempts.length === 1) throw new Error('network'); return snapshot({ submitted_turn_id: '5', turns: [turn()] }) } })
  try {
    f.state.draft.value = '请导出考勤'; await f.state.send(); await flush()
    assert.equal(attempts.length, 1); assert.ok(f.state.retryPending.value)
    f.state.draft.value = '不同问题'; await f.state.send(); assert.equal(attempts.length, 1)
    await f.state.retrySend()
    assert.deepEqual(attempts[0], attempts[1]); assert.equal(f.state.retryPending.value, false)
  } finally { f.stop() }
})

test('account, authorization or semester changes clear content and fence late sends', async () => {
  for (const change of [c => { c.key = 'user2' }, c => { c.key = 'user1:revision2' }, c => { c.semesterId = '4' }]) {
    let resolve
    const f = fixture({ send: () => new Promise(r => { resolve = r }) })
    try {
      f.state.draft.value = '旧问题'; const pending = f.state.send(); await flush()
      change(f.context); await flush(); resolve(snapshot({ submitted_turn_id: '5', turns: [turn()] })); await pending
      assert.equal(f.state.turns.value.length, 0); assert.equal(f.state.conversation.value, null)
      assert.equal(f.state.draft.value, ''); assert.equal(f.memory.size, 0)
    } finally { f.stop() }
  }
})

test('read authorization failure removes old content, actions and restore pointer', async () => {
  let fail = false
  const f = fixture({ read: async () => { if (fail) throw Object.assign(new Error('权限已变化'), { status: 403 }); return snapshot({ turns: [turn()] }) } }, { key: 'user1:revision1', collegeId: '1', semesterId: '2', id: '3' })
  try {
    await flush(); assert.equal(f.state.turns.value.length, 1)
    fail = true; await f.state.refresh()
    assert.equal(f.state.turns.value.length, 0); assert.equal(f.memory.size, 0); assert.ok(f.state.error.value)
  } finally { f.stop() }
})

test('older history merges by ID and the current tail stays visible after refresh', async () => {
  const f = fixture({ read: async (id, c, before) => before ? snapshot({ turns: [turn({ id: '4' })] }) : snapshot({ next_before_turn_id: '5', turns: [turn()] }) }, { key: 'user1:revision1', collegeId: '1', semesterId: '2', id: '3' })
  try {
    await flush(); await f.state.loadOlder(); await f.state.refresh()
    assert.deepEqual(Array.from(f.state.turns.value, row => row.id), ['4', '5'])
    assert.equal(f.state.beforeCursor.value, null)
  } finally { f.stop() }
})

test('new tail pagination becomes available as the conversation grows', async () => {
  let large = false
  const f = fixture({ read: async () => snapshot({ next_before_turn_id: large ? '5' : null, turns: [turn()] }) }, { key: 'user1:revision1', collegeId: '1', semesterId: '2', id: '3' })
  try {
    await flush(); large = true; await f.state.refresh()
    assert.equal(f.state.beforeCursor.value, '5')
  } finally { f.stop() }
})

test('closing the drawer pauses polling; reopening reads status without sending', async () => {
  const f = fixture()
  try {
    f.state.draft.value = '合成问题'; await f.state.send()
    f.context.active = false; await flush()
    const count = f.calls.length
    f.context.active = true; await flush()
    assert.equal(f.calls.length, count + 1); assert.equal(f.calls.at(-1)[0], 'read')
  } finally { f.stop() }
})

test('polling changes a queued message to a reply and stops at terminal work', async () => {
  const f = fixture({ read: async () => snapshot({ turns: [turn()] }) })
  try {
    f.state.draft.value = '合成问题'; await f.state.send()
    assert.equal(f.timers.size, 1); await f.poll()
    assert.equal(f.state.turns.value[0].state, 'SUCCEEDED'); assert.equal(f.timers.size, 0)
  } finally { f.stop() }
})

test('a completed reply continues polling while its real child task is pending', async () => {
  const f = fixture({ read: async () => snapshot({ turns: [turn({ actions: [action({ task_status: 'RUNNING' })] })] }) }, { key: 'user1:revision1', collegeId: '1', semesterId: '2', id: '3' })
  try {
    await flush(); assert.equal(f.timers.size, 1)
    f.context.active = false; await flush(); assert.equal(f.timers.size, 0)
  } finally { f.stop() }
})

test('unmount fences late create without storing or sending against the old context', async () => {
  let resolve
  const f = fixture({ create: () => new Promise(r => { resolve = r }) })
  f.state.draft.value = '旧问题'; const pending = f.state.send(); await flush(); f.stop()
  resolve(snapshot()); await pending
  assert.equal(f.memory.size, 0); assert.equal(f.calls.length, 0)
})

test('result-unknown conversation prevents new sends; new conversation never resends the old question', async () => {
  const f = fixture({ read: async () => snapshot({ state: 'UNCERTAIN', turns: [turn({ state: 'UNCERTAIN', reply: null })] }) }, { key: 'user1:revision1', collegeId: '1', semesterId: '2', id: '3' })
  try {
    await flush(); f.state.draft.value = '新问题'; await f.state.send(); assert.equal(f.calls.length, 0)
    f.state.newConversation(); assert.equal(f.state.conversation.value, null); assert.equal(f.state.draft.value, '')
    assert.equal(f.calls.length, 0)
  } finally { f.stop() }
})
