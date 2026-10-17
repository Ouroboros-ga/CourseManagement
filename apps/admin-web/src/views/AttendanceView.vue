<script setup lang="ts">
import { computed, watch } from 'vue'
import { useSessionStore } from '../stores/session'
import { usePageTabs } from '../composables/usePageTabs'
import { useStaffContext } from '../composables/useStaffContext'
import AttendanceRecords from '../components/attendance/AttendanceRecords.vue'
import StaffAttendancePanel from '../components/staff/StaffAttendancePanel.vue'
import ObjectionsView from './ObjectionsView.vue'
import type { StaffView } from '../api/staffRecords'

const session = useSessionStore()
const staff = useStaffContext()

// 本人页签按有效任职出现；学院管理页签仍只按原有权限出现，两者互不推导。
const tabs = computed(() => [
  ...(staff.canEnter.value && staff.views.value.teaching
    ? [{ id: 'my-teaching', label: '我的授课' }]
    : []),
  ...(staff.canEnter.value && staff.views.value.responsible
    ? [{ id: 'my-class', label: '我的班级' }]
    : []),
  ...(staff.canEnter.value && staff.views.value.responsible
    ? [{ id: 'my-objections', label: '我的待处理异议' }]
    : []),
  ...(session.hasPermission('attendance.read') ? [{ id: 'records', label: '考勤与现场照片' }] : []),
  ...(['objection.read', 'objection.final_review'].some(code => session.hasPermission(code))
    ? [{ id: 'objections', label: '学生异议' }]
    : [])
])
const tab = usePageTabs(() => tabs.value.map(row => row.id))

const panelView = computed<StaffView | null>(() => {
  if (tab.value === 'my-teaching') return 'teaching'
  if (tab.value === 'my-class') return 'responsible'
  return null
})

watch(tab, value => {
  if (value === 'my-teaching') staff.selectView('teaching')
  if (value === 'my-class' || value === 'my-objections') staff.selectView('responsible')
})
</script>
<template>
  <section>
    <header class="page-head">
      <h1>考勤与异议</h1>
      <p class="sub">
        有学院管理权限时按当前学院和学期查看；只有本人任职时进入“我的授课/我的班级”，
        服务端逐请求按有效关系收窄范围。异议针对具体考勤，一次审核生效并保留历史。
      </p>
    </header>
    <el-tabs v-model="tab"><el-tab-pane v-for="row in tabs" :key="row.id" :name="row.id" :label="row.label" /></el-tabs>
    <div class="tab-stage">
      <Transition name="tab-fade" mode="out-in">
        <StaffAttendancePanel v-if="panelView" :key="`self-${panelView}`" :view="panelView" />
        <ObjectionsView v-else-if="tab === 'my-objections'" key="my-objections" self-scope />
        <AttendanceRecords v-else-if="tab === 'records'" key="records" />
        <ObjectionsView v-else-if="tab === 'objections'" key="objections" />
      </Transition>
    </div>
  </section>
</template>
