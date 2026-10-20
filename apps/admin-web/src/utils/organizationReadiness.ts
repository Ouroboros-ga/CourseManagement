import type { GroupConfiguration, VolunteerGroup } from '../api/campus'
import type { GroupMember } from '../api/groupMembers'

export function countEffectiveMembers(rows: GroupMember[], semesterId: string, date: string): number {
  return new Set(rows.filter(row => row.semester_id === semesterId && row.status === 'ACTIVE'
    && row.effective_from <= date && date < row.effective_to).map(row => row.student_id)).size
}

export interface OrganizationReadinessInput {
  group: Pick<VolunteerGroup, 'status' | 'starts_on' | 'ends_on'>
  configuration: GroupConfiguration | null
  memberCount: number | null
  loaded: boolean
  error: string
  semesterOpen: boolean
  schedulingEnabled: boolean
  businessEnabled: boolean
  date: string
}
/** Entry to date-specific preview is distinct from today's member readiness; the server validates the selected dates. */
export function canPreviewOrganization(input: OrganizationReadinessInput): boolean {
  return input.loaded && !input.error && input.semesterOpen && input.businessEnabled && input.schedulingEnabled
    && input.group.status === 'ACTIVE' && !!input.configuration?.course_type_ids.length
    && (input.configuration.class_mode !== 'SPECIFIC' || !!input.configuration.class_ids?.length)
}
export function organizationReadiness(input: OrganizationReadinessInput): {
  ready: boolean; label: string; action: 'rules' | 'members' | 'enable' | 'manage'
} {
  const result = (label: string, action: 'rules' | 'members' | 'enable' | 'manage', ready = false) => ({ ready, label, action })
  if (!input.semesterOpen) return result('学期未开放，仅供查看', 'manage')
  if (!input.businessEnabled) return result('学院成员业务未开放', 'manage')
  if (!input.loaded || input.error || input.memberCount === null) return result('成员与规则尚待核对', 'members')
  if (!input.configuration?.course_type_ids.length || (input.configuration.class_mode === 'SPECIFIC' && !input.configuration.class_ids?.length)) return result('待设置查课范围', 'rules')
  if (input.memberCount === 0) return result('待添加有效成员', 'members')
  if (input.group.starts_on && input.date < input.group.starts_on || input.group.ends_on && input.date > input.group.ends_on) return result('组织不在有效期内', 'manage')
  if (input.group.status !== 'ACTIVE') return result('待启用组织', 'enable')
  if (!input.schedulingEnabled) return result('设置已核对，系统排班未开放', 'manage')
  return result('可进入排班预览', 'manage', true)
}
