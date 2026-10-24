<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { primaryPages, canAccessPage } from '../navigation/workspaceNavigation'
import { useStaffContext } from '../composables/useStaffContext'
import WorkspaceOverview from '../components/workspace/WorkspaceOverview.vue'
const session = useSessionStore()
const staff = useStaffContext()
const entries = computed(() => primaryPages.filter(row => row.id !== 'home' && canAccessPage(row.id, session)))
const descriptions: Record<string, string> = {
  academic: '导入课表、核对教学班、配置作息并发布给学生。', students: '维护当前学生档案、行政班、学籍及绑定。',
  organizations: '管理组织、本院成员、学期资格和请假。', inspections: '选择具体课次、范围抽查、生成任务和确认排班。',
  attendance: '查看考勤、现场照片及处理学生异议。', reports: '按当前学期查看统计和导出报告。'
}
// 本人入口只依赖有效任职关系；没有学院管理权限的教工同样可以进入自己的工作视图。
const selfEntries = computed(() => [
  ...(staff.views.value.teaching
    ? [{ id: 'my-teaching', label: '我的授课', to: { path: '/dashboard/attendance', query: { tab: 'my-teaching' } },
        description: '本人授课课次的查课结果、认定更正、指定课节教室与导出。' }]
    : []),
  ...(staff.views.value.responsible
    ? [{ id: 'my-class', label: '我的班级', to: { path: '/dashboard/attendance', query: { tab: 'my-class' } },
        description: '本人责任班级在被查课时的记录与汇总；未查课不计为缺勤。' },
      { id: 'my-objections', label: '我的待处理异议', to: { path: '/dashboard/attendance', query: { tab: 'my-objections' } },
        description: '本班学生提出的考勤异议，一次审核生效；外院任务只展示、不改判。' }]
    : [])
])
</script>
<template>
  <section>
    <header class="page-head"><h1>工作台</h1><p class="sub">{{ session.workspace?.name || '学校工作区' }} · {{ session.currentSemesterName }}</p></header>
    <el-alert title="新学期先核对学生与班级，再导入教务课表，最后准备组织成员并安排查课。档案与绑定会跨学期保留。" type="info" :closable="false" />
    <WorkspaceOverview />
    <div v-if="selfEntries.length" class="self-block">
      <h2 class="block-title">本人工作视图</h2>
      <p class="block-sub">按当前有效任职计算，与学院管理入口互不影响；同一人兼任多职时可分别进入。</p>
      <div class="entry-grid">
        <router-link v-for="entry in selfEntries" :key="entry.id" :to="entry.to" class="entry-card self">
          <h2>{{ entry.label }}</h2><p>{{ entry.description }}</p><span>进入处理 →</span>
        </router-link>
      </div>
    </div>
    <div class="entry-grid">
      <router-link v-for="entry in entries" :key="entry.id" :to="entry.path" class="entry-card">
        <h2>{{ entry.label }}</h2><p>{{ descriptions[entry.id] }}</p><span>进入处理 →</span>
      </router-link>
    </div>
    <p class="hint">资料数量不等于业务全部就绪；请按待处理事项核对名单、分类及排班预览。</p>
  </section>
</template>
<style scoped>
.entry-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; margin-top: 24px; }
.entry-card { border: 1px solid var(--line); border-radius: var(--radius-md); padding: 24px; text-decoration: none; color: var(--ink); background: var(--paper); }
.entry-card:hover { border-color: var(--blue); }
.entry-card.self { background: var(--paper); border-left: 3px solid var(--blue); }
.self-block { margin-top: 24px; }
.block-title { margin: 0; }
.block-sub { color: var(--ink-mute); font-size: var(--text-xs); margin: 4px 0 0; }
p, .hint { color: var(--ink-mute); font-size: var(--text-sm); line-height: 1.8; } span { font-size: var(--text-xs); color: var(--blue); }
</style>
