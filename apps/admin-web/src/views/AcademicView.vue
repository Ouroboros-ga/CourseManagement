<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { usePageTabs } from '../composables/usePageTabs'
import CampusWorkspace from '../components/workspace/CampusWorkspace.vue'
import ScheduleView from './ScheduleView.vue'
import ScopedAcademicBrowser from '../components/campus/ScopedAcademicBrowser.vue'
import CourseTypeManager from '../components/campus/CourseTypeManager.vue'
import CollegeTimeConfiguration from '../components/campus/CollegeTimeConfiguration.vue'
import AcademicPublication from '../components/campus/AcademicPublication.vue'
import ImportHome from '../components/academic/ImportHome.vue'
const session = useSessionStore()
const route = useRoute()
const router = useRouter()
// 学院独立作息是全校级节次之外的另一套数据，只有两个运行开关同时开启才可能配置；
// 开关未开时整页无内容可填，因此不显示页签，而不是留下一个只能读提示的空页签。
const collegeTimeReady = computed(() => !!session.campusRuntime?.business_scoped && !!session.campusRuntime?.scheduling)
const tabs = computed(() => [
  ...(session.hasPermission('academic.read') ? [{ id: 'timetable', label: '正式课表' }, { id: 'classes', label: '教学班与分类' }] : []),
  ...(['import.execute', 'course_schedule.import'].some(p => session.hasPermission(p)) ? [{ id: 'imports', label: '资料准备' }] : []),
  ...(session.hasPermission('academic.course_type.read') ? [{ id: 'types', label: '课程类型' }] : []),
  ...(session.hasPermission('academic.manage') && collegeTimeReady.value ? [{ id: 'time', label: '本院作息与校历' }] : []),
  ...(session.hasPermission('academic.manage') ? [{ id: 'publication', label: '发布给学生' }] : [])
])
const tab = usePageTabs(() => tabs.value.map(row => row.id))

// 新向导仅学院正式业务启用时可用；否则自动展示当前可用的旧兼容入口，不让教师二选一。
const canUseNewImport = computed(() => !!session.campusRuntime?.business_scoped && session.hasPermission('import.execute'))
const canUseLegacyImport = computed(() => session.hasPermission('import.execute') || session.hasPermission('course_schedule.import'))

// “批量生成自习”快捷入口：消费一次性的 selfStudy 查询参数后立即清理，避免切换页签重复触发。
const openSelfStudy = ref(false)
watch(
  () => route.query.selfStudy,
  async value => {
    if (value !== '1') return
    openSelfStudy.value = true
    const query = { ...route.query }
    delete query.selfStudy
    await router.replace({ query })
    await nextTick()
    openSelfStudy.value = false
  },
  { immediate: true }
)
</script>
<template>
  <section>
    <header class="page-head"><h1>教务资料</h1><p class="sub">维护本院教务资料。导入与发布分别确认，学生个人修改不会被覆盖。</p></header>
    <el-tabs v-model="tab"><el-tab-pane v-for="row in tabs" :key="row.id" :name="row.id" :label="row.label" /></el-tabs>
    <div class="tab-stage">
      <Transition name="tab-fade" mode="out-in">
        <ScheduleView v-if="tab === 'timetable'" key="timetable" mode="academic" :open-self-study="openSelfStudy" />
        <div v-else-if="tab === 'imports'" key="imports">
          <ImportHome v-if="canUseNewImport" />
          <ScheduleView v-else-if="canUseLegacyImport" mode="academic" :open-import="true" :import-only="true" />
          <el-result v-else icon="info" title="当前账号没有资料导入权限" sub-title="请联系学院教师管理员开通后再试。" />
        </div>
        <CampusWorkspace v-else key="workspace" v-slot="scope">
          <Transition name="tab-fade" mode="out-in">
            <div v-if="tab === 'classes'" key="classes">
              <ScopedAcademicBrowser :college-id="scope.collegeId" :capabilities="scope.college.capabilities" :course-types="scope.types" :allowed-kinds="['teaching-classes', 'courses']" />
            </div>
            <div v-else-if="tab === 'types'" key="types">
              <CourseTypeManager :college-id="scope.collegeId" :rows="scope.types" :can-manage="scope.can('academic.course_type.manage')" @changed="scope.reload" />
            </div>
            <CollegeTimeConfiguration v-else-if="tab === 'time'" key="time" :college-id="scope.collegeId" />
            <AcademicPublication v-else key="publication" :college-id="scope.collegeId" />
          </Transition>
        </CampusWorkspace>
      </Transition>
    </div>
  </section>
</template>
