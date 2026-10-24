import { computed, shallowRef, watch, onScopeDispose } from 'vue'
import { assistantConversationsApi as api, parseConversation, type Conversation, type ConversationScope, type ConversationTurn } from '../api/assistantConversations'
import { validAgentId } from '../api/assistantReports'
import { ContextEpoch } from '../utils/contextEpoch'

interface Context extends ConversationScope { key: string; available: boolean; active: boolean }
interface Options { storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>; pollIntervalMs?: number }
const pointerKey = 'management-assistant-conversation'
const message = (cause: unknown) => cause instanceof Error ? cause.message : '暂时无法读取助手，请刷新核对'
const compareId = (a: string, b: string) => a.length - b.length || a.localeCompare(b)

export function useManagementConversation(context: () => Context, options: Options = {}) {
  const conversation = shallowRef<Conversation | null>(null), turns = shallowRef<ConversationTurn[]>([])
  const draft = shallowRef(''), error = shallowRef(''), busy = shallowRef(false), loadingOlder = shallowRef(false)
  const beforeCursor = shallowRef<string | null>(null), retryPending = shallowRef(false)
  let conversationId = '', pending: { text: string; key: string } | null = null
  let disposed = false, timer: ReturnType<typeof setTimeout> | undefined, polls = 0, loadedOlder = false
  const key = () => JSON.stringify([context().key, context().collegeId, context().semesterId, context().available])
  const epoch = new ContextEpoch(key)
  let storage = options.storage
  try { storage ??= typeof window !== 'undefined' ? window.sessionStorage : undefined } catch { /* Storage may be disabled. */ }
  const scope = (): ConversationScope => ({ collegeId: context().collegeId, semesterId: context().semesterId })
  const available = () => !disposed && context().available && validAgentId(context().collegeId) && validAgentId(context().semesterId)
  const waiting = computed(() => turns.value.some(t => ['QUEUED', 'SENDING'].includes(t.state)))
  const canSend = computed(() => available() && !error.value && !busy.value && !loadingOlder.value && !waiting.value && !retryPending.value
    && (!conversation.value || conversation.value.state === 'OPEN'))
  function stopPolling() { if (timer !== undefined) clearTimeout(timer); timer = undefined }
  function forgetPointer() { try { storage?.removeItem(pointerKey) } catch { /* Optional recovery only. */ } }
  function remember() {
    try { storage?.setItem(pointerKey, JSON.stringify({ key: context().key, ...scope(), id: conversationId })) } catch { /* No message text is persisted. */ }
  }
  function clear() {
    epoch.invalidate(); stopPolling(); conversationId = ''; conversation.value = null; turns.value = []
    beforeCursor.value = null; pending = null; retryPending.value = false; busy.value = false
    loadingOlder.value = false; draft.value = ''; error.value = ''; polls = 0; loadedOlder = false
  }
  function apply(data: Conversation, older = false) {
    if (!loadedOlder || older) beforeCursor.value = data.next_before_turn_id
    if (older) loadedOlder = true
    conversationId = data.id
    const merged = new Map(turns.value.map(t => [t.id, t]))
    data.turns.forEach(t => merged.set(t.id, t))
    turns.value = [...merged.values()].sort((a, b) => compareId(a.id, b.id)).slice(-100)
    conversation.value = { ...data, turns: turns.value }
    remember()
  }
  function schedule() {
    stopPolling()
    const pendingTasks = turns.value.some(t => t.actions.some(a => ['QUEUED', 'RUNNING'].includes(a.task_status)))
    if (!available() || !context().active || error.value || !conversationId || polls >= 450 || (!waiting.value && !pendingTasks)) return
    timer = setTimeout(() => { polls++; void refresh(false) }, options.pollIntervalMs ?? 2000)
  }
  function failed(cause: unknown) {
    // Remove actionable stale data even when an authorization change looks like a transport failure.
    conversation.value = null; turns.value = []; beforeCursor.value = null; error.value = message(cause)
    const status = (cause as { status?: number } | null)?.status
    if ([401, 403, 404, 409].includes(status || 0)) { conversationId = ''; pending = null; retryPending.value = false; forgetPointer() }
  }
  async function refresh(manual = true) {
    if (!available() || !conversationId || busy.value || loadingOlder.value) return
    if (manual) polls = 0
    stopPolling(); const ticket = epoch.begin(), id = conversationId, currentScope = scope()
    busy.value = true; error.value = ''
    try {
      const data = parseConversation(await api.read(id, currentScope), currentScope, id)
      if (ticket.isCurrent()) apply(data)
    } catch (cause) { if (ticket.isCurrent()) failed(cause) }
    finally { if (ticket.isLatest()) { busy.value = false; schedule() } }
  }
  async function transmit(retry: boolean) {
    if (!available() || busy.value || loadingOlder.value) return
    if (retry ? !pending : !canSend.value || !draft.value.trim() || draft.value.length > 4000) return
    if (!retry) pending = { text: draft.value.trim(), key: crypto.randomUUID() }
    const request = pending!
    stopPolling(); const ticket = epoch.begin(), currentScope = scope()
    busy.value = true; error.value = ''; polls = 0
    try {
      if (!conversationId) {
        const created = parseConversation(await api.create(currentScope), currentScope)
        if (!ticket.isCurrent()) return
        apply(created)
      }
      const id = conversationId
      const data = parseConversation(await api.send(id, currentScope, request.text, request.key), currentScope, id)
      if (!ticket.isCurrent()) return
      if (!data.submitted_turn_id) throw new Error('发送回执不完整，请核对原请求')
      apply(data); pending = null; retryPending.value = false; draft.value = ''
    } catch (cause) {
      if (ticket.isCurrent()) { failed(cause); retryPending.value = pending !== null }
    } finally { if (ticket.isLatest()) { busy.value = false; schedule() } }
  }
  async function loadOlder() {
    if (!available() || busy.value || loadingOlder.value || !conversationId || !beforeCursor.value) return
    stopPolling(); const ticket = epoch.begin(), id = conversationId, currentScope = scope(), before = beforeCursor.value
    loadingOlder.value = true; error.value = ''
    try {
      const data = parseConversation(await api.read(id, currentScope, before), currentScope, id)
      if (ticket.isCurrent()) apply(data, true)
    } catch (cause) { if (ticket.isCurrent()) failed(cause) }
    finally { if (ticket.isLatest()) { loadingOlder.value = false; schedule() } }
  }
  function newConversation() { clear(); forgetPointer() }
  watch(key, (_value, previous) => {
    clear()
    if (previous !== undefined || !available()) { forgetPointer(); return }
    try {
      const stored = JSON.parse(storage?.getItem(pointerKey) || 'null')
      if (stored && stored.key === context().key && stored.collegeId === context().collegeId && stored.semesterId === context().semesterId && validAgentId(stored.id)) conversationId = stored.id
      else forgetPointer()
    } catch { forgetPointer() }
    if (context().active) void refresh()
  }, { immediate: true, flush: 'sync' })
  watch(() => context().active, active => { stopPolling(); if (active) void refresh() }, { flush: 'sync' })
  onScopeDispose(() => { disposed = true; epoch.invalidate(); stopPolling() })
  return { conversation, turns, draft, error, busy, loadingOlder, beforeCursor, retryPending, waiting, canSend,
    send: () => transmit(false), retrySend: () => transmit(true), refresh, loadOlder, newConversation }
}
