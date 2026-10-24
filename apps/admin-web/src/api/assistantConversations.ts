import { request } from './http'
import { validAgentId } from './assistantReports'

export interface ConversationScope { collegeId: string; semesterId: string }
export type TurnState = 'QUEUED' | 'SENDING' | 'SUCCEEDED' | 'FAILED' | 'UNCERTAIN'
export interface ConversationAction { task_id: string; task_status: string; open_path: string; title: string }
export interface ConversationTurn {
  id: string; state: TurnState; user_text: string; reply: string | null
  error_code: string | null; created_at: string; actions: ConversationAction[]
}
export interface Conversation {
  id: string; state: 'OPEN' | 'UNCERTAIN' | 'CLOSED'; college_id: string; semester_id: string
  next_before_turn_id: string | null; turns: ConversationTurn[]; submitted_turn_id?: string
}
const root = '/api/v1/assistant/management/conversations'
const states = ['QUEUED', 'SENDING', 'SUCCEEDED', 'FAILED', 'UNCERTAIN']
const taskStates = ['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELED']
function fail(): never { throw new Error('助手会话内容不完整或与当前学院、学期不一致，请重新核对') }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail()
  return value as Record<string, unknown>
}
function scopeBody(scope: ConversationScope) {
  if (!validAgentId(scope.collegeId) || !validAgentId(scope.semesterId)) return fail()
  return { college_id: scope.collegeId, semester_id: scope.semesterId }
}
function path(id: string) { if (!validAgentId(id)) return fail(); return `${root}/${id}` }
function parseAction(value: unknown): ConversationAction {
  const row = record(value)
  if (row.kind !== 'TASK_HANDOFF' || !validAgentId(row.task_id) || row.requires_login !== true
    || row.business_data_applied !== false || typeof row.task_status !== 'string' || !taskStates.includes(row.task_status)) return fail()
  const report = `/dashboard/reports?assistant_task_id=${row.task_id}`
  const imports = `/dashboard/academic?tab=imports&assistant_task_id=${row.task_id}`
  if (row.open_path !== report && row.open_path !== imports) return fail()
  return { task_id: row.task_id, task_status: row.task_status, open_path: row.open_path, title: row.open_path === report ? '查看报表任务' : '核对资料' }
}
function parseTurn(value: unknown): ConversationTurn {
  const row = record(value)
  if (!validAgentId(row.id) || typeof row.state !== 'string' || !states.includes(row.state)
    || typeof row.user_text !== 'string' || !row.user_text.trim() || row.user_text.length > 4000
    || (row.state === 'SUCCEEDED' ? typeof row.reply !== 'string' : row.reply !== null)
    || (typeof row.reply === 'string' && row.reply.length > 128 * 1024)
    || !(row.error_code === null || typeof row.error_code === 'string')
    || typeof row.created_at !== 'string' || !Number.isFinite(Date.parse(row.created_at))
    || !Array.isArray(row.actions) || row.actions.length > 100) return fail()
  const actions = row.actions.map(parseAction)
  if (new Set(actions.map(a => a.task_id)).size !== actions.length) return fail()
  return { id: row.id, state: row.state as TurnState, user_text: row.user_text,
    reply: row.reply as string | null, error_code: row.error_code as string | null,
    created_at: row.created_at, actions }
}
export function parseConversation(value: unknown, scope: ConversationScope, expectedId?: string): Conversation {
  scopeBody(scope)
  const row = record(value)
  if (!validAgentId(row.id) || (expectedId !== undefined && row.id !== expectedId)
    || row.college_id !== scope.collegeId || row.semester_id !== scope.semesterId
    || typeof row.state !== 'string' || !['OPEN', 'UNCERTAIN', 'CLOSED'].includes(row.state)
    || !(row.next_before_turn_id === null || validAgentId(row.next_before_turn_id))
    || !Array.isArray(row.turns) || row.turns.length > 20
    || (row.submitted_turn_id !== undefined && !validAgentId(row.submitted_turn_id))) return fail()
  const turns = row.turns.map(parseTurn)
  if (new Set(turns.map(t => t.id)).size !== turns.length) return fail()
  return { id: row.id, state: row.state as Conversation['state'], college_id: scope.collegeId,
    semester_id: scope.semesterId, next_before_turn_id: row.next_before_turn_id as string | null,
    turns, ...(row.submitted_turn_id !== undefined ? { submitted_turn_id: row.submitted_turn_id as string } : {}) }
}
export const assistantConversationsApi = {
  create: (scope: ConversationScope) => request<unknown>(root, { method: 'POST', body: JSON.stringify(scopeBody(scope)) }),
  read: (id: string, scope: ConversationScope, before?: string) => {
    const query = new URLSearchParams(scopeBody(scope))
    if (before !== undefined) { if (!validAgentId(before)) return fail(); query.set('before_turn_id', before) }
    return request<unknown>(`${path(id)}?${query}`)
  },
  send: (id: string, scope: ConversationScope, text: string, requestKey: string) => {
    if (!text.trim() || text.length > 4000 || !/^[A-Za-z0-9_-]{1,64}$/.test(requestKey)) return fail()
    return request<unknown>(`${path(id)}/messages`, { method: 'POST', body: JSON.stringify({ ...scopeBody(scope), text, request_key: requestKey }) })
  }
}
