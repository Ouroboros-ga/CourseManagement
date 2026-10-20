import { onScopeDispose } from 'vue'
import type { GroupConfiguration, VolunteerGroup } from '../api/campus'
import { groupMemberApi, type GroupMember } from '../api/groupMembers'
import { preparationSource } from '../api/organizationManagement'
import { useWorkspaceRead } from './useWorkspaceRead'

export interface OrganizationTerm {
  configuration: GroupConfiguration | null
  members: GroupMember[]
  specific: boolean
  error: string
}
interface Context { key: string; collegeId: string; semesterId: string; enabled: boolean; groups: VolunteerGroup[] }
/** Read actual term rules; a confirmed semester can differ from the organization's current default. */
export function useOrganizationOverview(context: () => Context) {
  let active = true
  onScopeDispose(() => { active = false })
  return useWorkspaceRead(
    () => `${context().key}:${context().groups.map(g => `${g.id}:${g.lock_version}:${g.config_version}`).join(',')}`,
    () => context().enabled && !!context().semesterId,
    async () => {
      const scope = context(), result: Record<string, OrganizationTerm> = {}
      let next = 0
      async function worker() {
        while (active && context().enabled && context().key === scope.key && next < scope.groups.length) {
          const group = scope.groups[next++]!
          try {
            if (group.config_version > 0) {
              const row = await preparationSource(scope.collegeId, group.id, scope.semesterId, scope.semesterId)
              result[group.id] = { configuration: row.configuration, members: row.members, specific: row.uses_semester_specific_rules, error: '' }
            } else {
              const members = await groupMemberApi.list('members', scope.collegeId, group.id, scope.semesterId)
              result[group.id] = { configuration: null, members, specific: false, error: '' }
            }
          } catch (e) {
            result[group.id] = { configuration: null, members: [], specific: false, error: e instanceof Error ? e.message : '读取组织资料失败' }
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(4, scope.groups.length) }, worker))
      return result
    }
  )
}
