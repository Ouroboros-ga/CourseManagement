<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { usePageTabs } from '../composables/usePageTabs'
import VolunteersView from './VolunteersView.vue'
import CampusWorkspace from '../components/workspace/CampusWorkspace.vue'
import StudentHandoff from '../components/campus/StudentHandoff.vue'
import EnrollmentHistory from '../components/students/EnrollmentHistory.vue'
const session = useSessionStore()
const tabs = computed(() => ['directory', ...(session.hasPermission('student.read') ? ['history'] : []), ...(session.hasPermission('student.manage') ? ['handoff'] : [])])
const tab = usePageTabs(() => tabs.value)
</script>
<template>
  <section>
    <header class="page-head"><h1>学生与班级</h1><p class="sub">当前学生档案、行政班和绑定持续保留；学籍变化按生效日期记录。</p></header>
    <el-tabs v-model="tab"><el-tab-pane name="directory" label="学生、行政班与绑定" /><el-tab-pane v-if="tabs.includes('history')" name="history" label="按日期查看学籍" /><el-tab-pane v-if="tabs.includes('handoff')" name="handoff" label="学籍变更与交接" /></el-tabs>
    <div class="tab-stage">
      <Transition name="tab-fade" mode="out-in">
        <VolunteersView v-if="tab === 'directory'" key="directory" mode="students" />
        <EnrollmentHistory v-else-if="tab === 'history'" key="history" />
        <CampusWorkspace v-else key="handoff" v-slot="scope"><StudentHandoff :college-id="scope.collegeId" /></CampusWorkspace>
      </Transition>
    </div>
  </section>
</template>
