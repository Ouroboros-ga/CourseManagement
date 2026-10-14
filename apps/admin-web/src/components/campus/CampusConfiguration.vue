<script setup lang="ts">
import { useCampusConfiguration } from '../../composables/useCampusConfiguration'
import CourseTypeManager from './CourseTypeManager.vue'
import GroupManager from './GroupManager.vue'
import CampusAdministration from './CampusAdministration.vue'
import OwnershipReconciliation from './OwnershipReconciliation.vue'
import ScopedAcademicBrowser from './ScopedAcademicBrowser.vue'

const { colleges, collegeId, college, types, groups, error, busy, userId, isSuper, can, reload, loadWorkspaces } = useCampusConfiguration()
</script>
<template>
  <section class="campus-page">
    <h1>学院与组织配置</h1>
    <p>维护学院配置、课程分类与志愿者组织。</p>
    <el-alert title="配置底座阶段：课程类型和组规则尚未接入现有课表及排班，当前仍沿用原业务流程。" type="info" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="toolbar">
      <el-select v-model="collegeId" placeholder="选择学院" :disabled="busy" aria-label="当前学院">
        <el-option v-for="row in colleges" :key="row.id" :value="row.id" :label="`${row.name}${row.status === 'INACTIVE' ? '（停用）' : ''}`" />
      </el-select>
      <el-button :loading="busy" @click="loadWorkspaces">刷新学院与权限</el-button>
    </div>
    <el-empty v-if="!collegeId && !isSuper && !error" description="尚未获得学院配置授权，请联系超级管理员" />
    <el-tabs v-if="(college || isSuper) && !error" v-loading="busy">
      <el-tab-pane v-if="isSuper" label="学院与授权">
        <CampusAdministration :key="`admin:${userId}:${collegeId}`" :college="college" @changed="loadWorkspaces" />
      </el-tab-pane>
      <el-tab-pane v-if="isSuper" label="存量归属核对">
        <OwnershipReconciliation :key="`ownership:${userId}`" :colleges="colleges" />
      </el-tab-pane>
      <el-tab-pane v-if="college && ['academic.read', 'student.read', 'volunteer.read'].some(action => can(action))" label="本院基础数据">
        <ScopedAcademicBrowser :key="`data:${userId}:${collegeId}:${college.authorization_revision}`" :college-id="collegeId" :capabilities="college.capabilities" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('academic.course_type.read')" label="课程类型">
        <CourseTypeManager :key="`types:${userId}:${collegeId}`" :college-id="collegeId" :rows="types" :can-manage="can('academic.course_type.manage')" @changed="reload" />
      </el-tab-pane>
      <el-tab-pane v-if="college && can('volunteer.group.read')" label="志愿者组">
        <GroupManager :key="`groups:${userId}:${collegeId}`" :college-id="collegeId" :rows="groups" :types="types" :user-id="userId" :can-manage="can('volunteer.group.manage')" :can-publish="can('volunteer.config.publish')" @changed="reload" />
      </el-tab-pane>
    </el-tabs>
  </section>
</template>
<style scoped>
.campus-page { padding: 24px; max-width: 1400px; margin: auto; }
.toolbar { display: flex; gap: 12px; margin: 20px 0; flex-wrap: wrap; }
.campus-page :deep(.el-alert) { margin: 12px 0; }
</style>
