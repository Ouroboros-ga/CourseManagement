import { onScopeDispose, shallowRef, watch } from 'vue'
import { listCourseTypes, listGroups, type CourseType, type VolunteerGroup } from '../api/campus'

interface Context { collegeId: string; userId: string; enabled: boolean; readTypes: boolean; readGroups: boolean }
export function useDispatchOptions(context: () => Context) {
  const types = shallowRef<CourseType[]>([]), groups = shallowRef<VolunteerGroup[]>([]), error = shallowRef('')
  let revision = 0
  watch(() => JSON.stringify(context()), async () => {
    const ticket = ++revision, scope = context()
    types.value = []; groups.value = []; error.value = ''
    if (!scope.enabled || !scope.collegeId || !scope.userId) return
    try {
      const rows = await Promise.all([
        scope.readTypes ? listCourseTypes(scope.collegeId) : Promise.resolve([]),
        scope.readGroups ? listGroups(scope.collegeId) : Promise.resolve([])
      ])
      if (ticket !== revision) return
      types.value = rows[0]; groups.value = rows[1]
    } catch (e) { if (ticket === revision) error.value = e instanceof Error ? e.message : '课程类型或执行组读取失败' }
  }, { immediate: true })
  onScopeDispose(() => { revision++ })
  return { types, groups, error }
}
