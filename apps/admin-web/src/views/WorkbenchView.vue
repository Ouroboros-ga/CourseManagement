<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { primaryPages, canAccessPage } from '../navigation/workspaceNavigation'
import WorkspaceOverview from '../components/workspace/WorkspaceOverview.vue'
const session = useSessionStore()
const entries = computed(() => primaryPages.filter(row => row.id !== 'home' && canAccessPage(row.id, session)))
const descriptions: Record<string, string> = {
  academic: '导入课表、核对教学班、配置作息并发布给学生。', students: '维护当前学生档案、行政班、学籍及绑定。',
  organizations: '管理组织、成员、学期资格和请假支援。', inspections: '选择具体课次、范围抽查、生成任务和确认排班。',
  attendance: '查看考勤、现场照片及处理学生异议。', reports: '按当前学期查看统计和导出报告。'
}
</script>
<template>
  <section>
    <header class="page-head"><h1>工作台</h1><p class="sub">{{ session.workspace?.name || '学校工作区' }} · {{ session.currentSemesterName }}</p></header>
    <el-alert title="新学期先核对学生与班级，再导入教务课表，最后准备组织成员并安排查课。档案与绑定会跨学期保留。" type="info" :closable="false" />
    <WorkspaceOverview />
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
.entry-card { border: 1px solid var(--line); border-radius: 8px; padding: 24px; text-decoration: none; color: var(--ink); background: var(--paper); }
.entry-card:hover { border-color: var(--blue); }
h2 { font-size: 18px; } p, .hint { color: var(--ink-mute); font-size: 13px; line-height: 1.8; } span { font-size: 12px; color: var(--blue); }
</style>
