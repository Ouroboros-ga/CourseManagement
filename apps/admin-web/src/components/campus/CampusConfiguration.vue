<script setup lang="ts">
import ConfigurationImpacts from './ConfigurationImpacts.vue'
import { computed } from 'vue'
import { useSessionStore } from '../../stores/session'
import { useCampusConfiguration } from '../../composables/useCampusConfiguration'
import CourseTypeManager from './CourseTypeManager.vue'
import GroupManager from './GroupManager.vue'
import CampusAdministration from './CampusAdministration.vue'
import OwnershipReconciliation from './OwnershipReconciliation.vue'
import ScopedAcademicBrowser from './ScopedAcademicBrowser.vue'
import AcademicPublication from './AcademicPublication.vue'
import CollegeTimeConfiguration from './CollegeTimeConfiguration.vue'
import CollegeDeadlines from './CollegeDeadlines.vue'
import StudentHandoff from './StudentHandoff.vue'
import GroupOperations from './GroupOperations.vue'

const { colleges, collegeId, college, types, groups, error, busy, userId, isSuper, can, reload, loadWorkspaces } = useCampusConfiguration()
const session = useSessionStore()
const businessReady = computed(() => !!session.campusRuntime?.business_scoped)
const schedulingReady = computed(() => businessReady.value && !!session.campusRuntime?.scheduling)
</script>
<template>
  <section class="campus-page">
    <header class="page-head">
      <h1>学院与组织配置</h1>
      <p class="sub">维护学院配置、课程分类与志愿者组织。</p>
    </header>
    <el-alert title="启用多学院业务前，请完成存量数据归属核对。作息调整会保留已生成任务的时间快照。" type="info" :closable="false" />
    <el-alert v-if="!schedulingReady" title="作息计算、组成员与组织排班尚未启用。相关入口暂不可操作，类型/组配置和教务发布仍可按授权使用。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="toolbar">
      <el-select v-model="collegeId" placeholder="选择学院" :disabled="busy" aria-label="当前学院">
        <el-option v-for="row in colleges" :key="row.id" :value="row.id" :label="`${row.name}${row.status === 'INACTIVE' ? '（停用）' : ''}`" />
      </el-select>
      <el-button :loading="busy" @click="loadWorkspaces">刷新学院与权限</el-button>
    </div>
    <el-empty v-if="!collegeId && !isSuper && !error" description="尚未获得学院配置授权，请联系超级管理员" />
    <el-tabs v-if="(college || isSuper) && !error" v-loading="busy" class="tabs-embed">
      <el-tab-pane v-if="isSuper" label="学院与授权">
        <CampusAdministration :key="`admin:${userId}:${collegeId}`" :college="college" @changed="loadWorkspaces" />
      </el-tab-pane>
      <el-tab-pane v-if="isSuper" label="存量归属核对">
        <OwnershipReconciliation :key="`ownership:${userId}`" :colleges="colleges" />
      </el-tab-pane>
      <el-tab-pane v-if="college && ['academic.read', 'student.read', 'volunteer.read'].some(action => can(action))" label="本院基础数据">
        <ScopedAcademicBrowser :key="`data:${userId}:${collegeId}:${college.authorization_revision}`" :college-id="collegeId" :capabilities="college.capabilities" :course-types="types" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('student.manage')" label="学生交接与学籍"><StudentHandoff :key="`handoff:${userId}:${collegeId}`" :college-id="collegeId" /></el-tab-pane>
      <el-tab-pane v-if="college && can('academic.course_type.read')" label="课程类型">
        <CourseTypeManager :key="`types:${userId}:${collegeId}`" :college-id="collegeId" :rows="types" :can-manage="can('academic.course_type.manage')" @changed="reload" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('academic.manage')" label="教务课表发布">
        <AcademicPublication :key="`publication:${userId}:${collegeId}:${college.authorization_revision}`" :college-id="collegeId" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('academic.manage')" label="学院作息与校历" :disabled="!schedulingReady">
        <CollegeTimeConfiguration v-if="schedulingReady" :key="`time:${userId}:${collegeId}:${college.authorization_revision}`" :college-id="collegeId" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('volunteer.group.read')" label="志愿者组">
        <GroupManager :key="`groups:${userId}:${collegeId}`" :college-id="collegeId" :rows="groups" :types="types" :user-id="userId" :can-manage="can('volunteer.group.manage')" :can-publish="can('volunteer.config.publish')" @changed="reload" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('submission_deadline.read')" label="本院提交截止" :disabled="!businessReady" lazy>
        <CollegeDeadlines v-if="businessReady" :key="`deadline:${userId}:${collegeId}:${college.authorization_revision}`" :college-id="collegeId" :can-manage="can('submission_deadline.manage')" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('volunteer.group.read')" label="组织成员、抽查与排班" :disabled="!schedulingReady" lazy>
        <GroupOperations v-if="schedulingReady" :key="`operations:${userId}:${collegeId}:${college.authorization_revision}`"
          :college-id="collegeId" :groups="groups" :capabilities="college.capabilities" :is-super="isSuper" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('inspection.read')" label="变更影响处置" :disabled="!businessReady" lazy>
        <ConfigurationImpacts v-if="businessReady" :key="`impact:${userId}:${collegeId}`" :college-id="collegeId" :capabilities="college.capabilities" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
<style scoped>
.campus-page { padding: 24px; max-width: 1400px; margin: auto; }
.toolbar { display: flex; gap: 12px; margin: 20px 0; flex-wrap: wrap; }
.campus-page :deep(.el-alert) { margin: 12px 0; }
</style>
