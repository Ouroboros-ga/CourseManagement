<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { usePageTabs } from '../composables/usePageTabs'
import AttendanceRecords from '../components/attendance/AttendanceRecords.vue'
import ObjectionsView from './ObjectionsView.vue'
const session = useSessionStore()
const tabs = computed(() => [
  ...(session.hasPermission('attendance.read') ? [{ id: 'records', label: '考勤与现场照片' }] : []),
  ...(['objection.read', 'objection.final_review'].some(code => session.hasPermission(code)) ? [{ id: 'objections', label: '学生异议' }] : [])
])
const tab = usePageTabs(() => tabs.value.map(row => row.id))
</script>
<template>
  <section>
    <header class="page-head"><h1>考勤与异议</h1><p class="sub">按当前学院和学期查看记录。异议针对具体考勤，一次审核生效并保留历史。</p></header>
    <el-tabs v-model="tab"><el-tab-pane v-for="row in tabs" :key="row.id" :name="row.id" :label="row.label" /></el-tabs>
    <div class="tab-stage">
      <Transition name="tab-fade" mode="out-in">
        <AttendanceRecords v-if="tab === 'records'" key="records" />
        <ObjectionsView v-else-if="tab === 'objections'" key="objections" />
      </Transition>
    </div>
  </section>
</template>
