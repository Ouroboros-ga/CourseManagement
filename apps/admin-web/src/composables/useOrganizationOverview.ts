import type { GroupConfiguration, VolunteerGroup } from '../api/campus'
import type { GroupMember } from '../api/groupMembers'
import { organizationOverview } from '../api/organizationManagement'
import { useWorkspaceRead } from './useWorkspaceRead'

export interface OrganizationTerm {
  configuration: GroupConfiguration | null
  members: GroupMember[]
  member_count?: number
  specific: boolean
  error: string
}
interface Context { asOf?: string; key: string; collegeId: string; semesterId: string; enabled: boolean; groups: VolunteerGroup[] }
/** Read actual term rules; a confirmed semester can differ from the organization's current default. */
export function useOrganizationOverview(context: () => Context) {
  return useWorkspaceRead(
    () => `${context().key}:${context().asOf || ''}:${context().groups.map(g => `${g.id}:${g.lock_version}:${g.config_version}`).join(',')}`,
    () => context().enabled && !!context().semesterId && context().groups.length > 0,
    async () => {
      const scope = context()
      try {
        const result = await organizationOverview(scope.collegeId, scope.semesterId, scope.asOf)
        return Object.fromEntries(scope.groups.map(group => [group.id, result.items[group.id]
          ? { ...result.items[group.id], members: [] }
          : { configuration: null, members: [], specific: false, error: '组织摘要不可读取，请刷新权限' }])) as Record<string, OrganizationTerm>
      } catch (error) {
        return Object.fromEntries(scope.groups.map(group => [group.id, { configuration: null,
          members: [], specific: false, error: error instanceof Error ? error.message : '读取组织摘要失败' }])) as Record<string, OrganizationTerm>
      }
    }
  )
}
