/** Explicit workspace routing for management APIs; personal/file/auth calls remain independent. */
import { ApiError, request as httpRequest } from './http'

export interface CampusRuntime { academic_scoped: boolean; business_scoped: boolean; scheduling: boolean; objection_precheck?: boolean }
let runtime: CampusRuntime | null = null
let collegeId = ''
let revision = 0
export const isAcademicScoped = () => !!runtime?.academic_scoped

export function configureWorkspace(next: CampusRuntime | null, cid: string) {
  if (JSON.stringify(runtime) !== JSON.stringify(next) || cid !== collegeId) revision += 1
  runtime = next; collegeId = cid
}

export function workspaceUrl(url: string, method = 'GET'): string {
  if (!url.startsWith('/api/v1/') || url.startsWith('/api/v1/colleges/')) return url
  const suffix = url.slice('/api/v1'.length)
  const academic = suffix.startsWith('/academic/') || suffix.startsWith('/course-schedules/')
  const shared = /^\/academic\/semesters(?:[/?]|$)/.test(suffix)
    && !suffix.includes('/reset-data') && !suffix.includes('/reset-preview')
  if (shared) return url
  const business = /^\/(?:inspection-tasks|inspection-course-occurrences|inspection-volunteers|inspection\/volunteers|assignments|assignment-change-requests|management\/submissions|submissions|attendance|objections|statistics|reports|report-versions|imports|import-templates|audit-logs)(?:[/?]|$)/.test(suffix)
    || /^\/submission-deadlines(?:[/?]|$)/.test(suffix)
    || /^\/(?:role-assignment-targets|optional-permission-targets)(?:[/?]|$)/.test(suffix)
    || /^\/(?:students\/(?:[^/]+\/binding-tokens|batch-binding-tokens|export-binding-tokens)|binding-tokens\/[^/]+\/revoke|users\/[^/]+\/student-binding-reset)(?:[/?]|$)/.test(suffix)
  if (!academic && !business) return url
  if (!runtime) throw new ApiError(409, { code: 'WORKSPACE_REQUIRED', message: '学院上下文尚未加载，请刷新学院权限' })
  if (!(academic ? runtime.academic_scoped : runtime.business_scoped)) return url
  if (!collegeId) throw new ApiError(409, { code: 'WORKSPACE_REQUIRED', message: '请先选择已授权学院' })
  let scoped = suffix
  if (academic) scoped = scoped.replace('/academic/course-schedules', '/academic/schedules')
    .replace('/academic/volunteer-qualifications', '/academic/qualifications')
  // Resolve before any network operation, so a retry cannot change its destination.
  void method
  return `/api/v1/colleges/${encodeURIComponent(collegeId)}${scoped}`
}

export async function request<T = unknown>(...args: Parameters<typeof httpRequest<T>>): Promise<T> {
  const captured = revision
  const [url, init = {}, retry = false, responseType = 'json'] = args
  const result = await httpRequest<T>(workspaceUrl(url, init.method), init, retry, responseType)
  if (captured !== revision) throw new ApiError(409, { code: 'WORKSPACE_CHANGED', message: '学院上下文已变化，请重新加载' })
  return result
}
