import { computed, ref, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { ContextEpoch } from '../utils/contextEpoch'
import type { StaffView } from '../api/staffRecords'

const STORAGE_KEY = 'staff_active_view'

/** 本人工作视图上下文：账号 + 档案 + 视图 + 学期 + 任职修订。
 *
 * 视图切换或任职变化时先失效旧请求（名单、照片、待提交表单不再回填），再按新视图加载；
 * 这里只提供入口与视图信息，真实授权逐请求由服务端按有效关系判定。
 */
export function useStaffContext() {
  const session = useSessionStore()

  const staffId = computed(() => session.staffContext?.staff_id || '')
  const views = computed(() => session.staffViews)
  const canEnter = computed(() => views.value.teaching || views.value.responsible)

  function preferred(): StaffView {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'teaching' && views.value.teaching) return 'teaching'
    if (stored === 'responsible' && views.value.responsible) return 'responsible'
    // 兼任时默认授课视图；纯辅导员只有责任班级视图，不需要额外提示。
    if (views.value.teaching) return 'teaching'
    return 'responsible'
  }

  const activeView = ref<StaffView>(preferred())

  // 任职变化（如撤销后下一次读取即失效）自动收敛到仍可用的视图。
  watch(views, next => {
    if (next[activeView.value]) return
    const fallback = next.teaching ? 'teaching' : next.responsible ? 'responsible' : null
    if (fallback) activeView.value = fallback as StaffView
  })

  function selectView(view: StaffView) {
    if (!views.value[view]) return
    epoch.invalidate()
    activeView.value = view
    localStorage.setItem(STORAGE_KEY, view)
  }

  const contextKey = computed(() => JSON.stringify([
    session.currentUser?.id || '',
    staffId.value,
    activeView.value,
    session.currentSemesterId || '',
    // 档案归属或账号变化后，旧请求不得回写当前视图。
    String(session.workspace?.authorization_revision || '')
  ]))

  const epoch = new ContextEpoch(() => contextKey.value)

  const tabs = computed(() => [
    ...(views.value.teaching ? [{ id: 'teaching' as StaffView, label: '我的授课' }] : []),
    ...(views.value.responsible ? [{ id: 'responsible' as StaffView, label: '我的班级' }] : [])
  ])

  return { activeView, canEnter, contextKey, epoch, selectView, staffId, tabs, views }
}
