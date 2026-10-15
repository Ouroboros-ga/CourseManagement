<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { usePageTabs } from '../composables/usePageTabs'
import ScheduleView from './ScheduleView.vue'
import TaskListView from './TaskListView.vue'
import CampusWorkspace from '../components/workspace/CampusWorkspace.vue'
import GroupOperations from '../components/campus/GroupOperations.vue'
import ConfigurationImpacts from '../components/campus/ConfigurationImpacts.vue'
import CollegeDeadlines from '../components/campus/CollegeDeadlines.vue'
const session = useSessionStore()
const tabs = computed(() => [
  ...(session.hasPermission('inspection.read') || session.hasPermission('submission.read') ? [{ id: 'tasks', label: '任务与排班' }] : []),
  ...(session.hasPermission('inspection.generate') ? [{ id: 'selection', label: '选择具体课次' }, { id: 'sampling', label: '组范围抽查' }] : []),
  ...(session.hasPermission('inspection.read') ? [{ id: 'impacts', label: '未来变更处置' }] : []),
  ...(session.hasPermission('submission_deadline.read') ? [{ id: 'deadlines', label: '提交截止' }] : [])
])
const tab = usePageTabs(() => tabs.value.map(row => row.id))
</script>
<template>
  <section>
    <header class="page-head"><h1>查课安排</h1><p class="sub">先生成任务，再确认排班。排班未完成时保留已生成任务。</p></header>
    <el-tabs v-model="tab"><el-tab-pane v-for="row in tabs" :key="row.id" :name="row.id" :label="row.label" /></el-tabs>
    <TaskListView v-if="tab === 'tasks'" />
    <ScheduleView v-else-if="tab === 'selection'" mode="inspection" />
    <CampusWorkspace v-else v-slot="scope">
      <GroupOperations v-if="tab === 'sampling' && session.campusRuntime?.business_scoped && session.campusRuntime?.scheduling" mode="sampling" :college-id="scope.collegeId" :groups="scope.groups" :capabilities="scope.college.capabilities" :is-super="scope.isSuper" />
      <ConfigurationImpacts v-else-if="tab === 'impacts' && session.campusRuntime?.business_scoped" :college-id="scope.collegeId" :capabilities="scope.college.capabilities" />
      <CollegeDeadlines v-else-if="tab === 'deadlines' && session.campusRuntime?.business_scoped" :college-id="scope.collegeId" :can-manage="scope.can('submission_deadline.manage')" />
      <el-alert v-else title="该学院业务能力尚未启用；请使用当前已开放入口或联系管理员确认准备情况。" type="info" :closable="false" />
    </CampusWorkspace>
  </section>
</template>
