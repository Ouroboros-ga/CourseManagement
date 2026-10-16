import { computed, onUnmounted, shallowRef, watch } from 'vue'
import { previewAcademicPublication, publishAcademicTimetable, type PublicationPreview } from '../api/academicPublication'
import { useSessionStore } from '../stores/session'
import { ContextEpoch, identityContext } from '../utils/contextEpoch'

export function useAcademicPublication(collegeId: () => string) {
  const session = useSessionStore()
  const semesterId = shallowRef('')
  const previewResult = shallowRef<PublicationPreview | null>(null)
  const busy = shallowRef(false), error = shallowRef(''), message = shallowRef('')
  const context = computed(() => `${identityContext(session.currentUser)}:${collegeId()}:${semesterId.value}`)
  const epoch = new ContextEpoch(() => context.value)
  watch(context, () => {
    epoch.invalidate(); previewResult.value = null; busy.value = false; error.value = ''; message.value = ''
  }, { flush: 'sync' })
  onUnmounted(() => epoch.invalidate())

  async function preview() {
    if (!collegeId() || !semesterId.value || busy.value) return
    const cid = collegeId(), sid = semesterId.value, ticket = epoch.begin()
    previewResult.value = null; busy.value = true; error.value = ''; message.value = ''
    try {
      const value = await previewAcademicPublication(cid, sid)
      if (ticket.isCurrent()) previewResult.value = value
    } catch (e) {
      if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '发布预览失败'
    } finally { if (ticket.isLatest()) busy.value = false }
  }
  async function publish() {
    const value = previewResult.value
    if (!value || !collegeId() || !semesterId.value || busy.value) return
    const cid = collegeId(), sid = semesterId.value, ticket = epoch.begin()
    busy.value = true; error.value = ''; message.value = ''
    try {
      const result = await publishAcademicTimetable(cid, sid, value.source_revision)
      if (!ticket.isCurrent()) return
      previewResult.value = null
      message.value = result.changed ? `已发布第 ${result.version} 版；已有个人课表保留，相关学生可查看更新通知。` : '内容与当前发布相同，未产生新版本或重复通知。'
    } catch (e) {
      if (ticket.isCurrent()) {
        previewResult.value = null
        error.value = e instanceof Error ? e.message : '发布失败，请重新预览'
      }
    } finally { if (ticket.isLatest()) busy.value = false }
  }
  return { semesterId, previewResult, busy, error, message, preview, publish }
}
