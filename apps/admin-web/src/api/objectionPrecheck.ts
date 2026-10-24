import { request } from './http'

export interface PrecheckResult {
  recommendation: 'SUPPORT' | 'NEEDS_INFORMATION' | 'NEEDS_VERIFICATION'
  summary: string
  evidence: { source: 'APPLICATION' | 'ATTENDANCE' | 'PROOF'; file_id: string | null; page: number | null; quote: string | null; observation: string }[]
  questions: string[]
}
export interface ObjectionPrecheck {
  objection_id: string
  job_id: string | null
  status: 'NOT_STARTED' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'STALE'
  stored_status: string | null
  is_current: boolean
  result: PrecheckResult | null
  can_retry: boolean
  retry_block_message: string | null
  can_final_review: boolean
  manual_reason_required: boolean
  review_block_reason: string | null
  final_status: string
}
export interface PrecheckReviewFields { precheck_job_id?: string | null; manual_precheck_reason?: string }
export interface ObjectionPrecheckPolicy { enabled: boolean; version: number; configuration_ready: boolean }
const policyPath = (cid: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/objection-precheck-policy`
export const objectionPrecheckPolicyApi = {
  get: (cid: string) => request<ObjectionPrecheckPolicy>(policyPath(cid)),
  update: (cid: string, body: { enabled: boolean; current_version: number }) =>
    request<ObjectionPrecheckPolicy>(policyPath(cid), { method: 'PUT', body: JSON.stringify(body) })
}
const path = (cid: string, id: string) => `/api/v1/colleges/${encodeURIComponent(cid)}/objections/${encodeURIComponent(id)}/precheck`
export const objectionPrecheckApi = {
  get: (cid: string, id: string) => request<ObjectionPrecheck>(path(cid, id)),
  retry: (cid: string, id: string, body: { expected_job_id: string | null }) =>
    request<ObjectionPrecheck>(`${path(cid, id)}/retry`, { method: 'POST', body: JSON.stringify(body) })
}
