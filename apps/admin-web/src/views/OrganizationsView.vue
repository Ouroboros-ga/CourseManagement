<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { usePageTabs } from '../composables/usePageTabs'
import CampusWorkspace from '../components/workspace/CampusWorkspace.vue'
import GroupManager from '../components/campus/GroupManager.vue'
import GroupOperations from '../components/campus/GroupOperations.vue'
import GroupSemesterPreparation from '../components/campus/GroupSemesterPreparation.vue'
import PermissionSources from '../components/campus/PermissionSources.vue'
import VolunteersView from './VolunteersView.vue'
const session = useSessionStore()
const tabs = computed(() => [
  ...(session.hasPermission('volunteer.group.read') ? [{ id: 'groups', label: '组织与规则' }, { id: 'members', label: '成员、支援与请假' }] : []),
  ...(session.hasPermission('volunteer.member.manage') && session.hasPermission('volunteer.config.publish') ? [{ id: 'preparation', label: '学期准备' }] : []),
  ...(session.hasPermission('volunteer.read') ? [{ id: 'qualifications', label: '本学期资格' }] : [])
])
const tab = usePageTabs(() => tabs.value.map(row => row.id))
</script>
<template>
  <section>
    <header class="page-head"><h1>志愿者组织</h1><p class="sub">组织持续存在，成员、资格和支援按学期与有效期核对。</p></header>
    <el-tabs v-model="tab"><el-tab-pane v-for="row in tabs" :key="row.id" :name="row.id" :label="row.label" /></el-tabs>
    <VolunteersView v-if="tab === 'qualifications'" mode="qualifications" />
    <CampusWorkspace v-else v-slot="scope">
      <PermissionSources v-if="session.campusRuntime?.business_scoped && session.campusRuntime?.scheduling" :college-id="scope.collegeId" />
      <p v-if="tab === 'groups'">这里维护跨学期的组织默认规则。已完成学期准备的学期使用独立确认的规则；修改默认规则不会覆盖已准备学期或已有任务。</p>
      <GroupSemesterPreparation v-if="tab === 'preparation' && session.currentSemester?.status === 'ACTIVE' && session.campusRuntime?.business_scoped && session.campusRuntime?.scheduling" :college-id="scope.collegeId" :groups="scope.groups" :types="scope.types" />
      <el-alert v-else-if="tab === 'preparation'" title="请选择已开放的目标学期，且先完成组织业务启用；归档学期不进行准备写入。" type="info" :closable="false" />
      <GroupManager v-if="tab === 'groups'" :college-id="scope.collegeId" :rows="scope.groups" :types="scope.types" :user-id="scope.userId" :can-manage="scope.can('volunteer.group.manage')" :can-publish="scope.can('volunteer.config.publish')" @changed="scope.reload" />
      <template v-if="tab === 'members'">
        <GroupOperations v-if="session.campusRuntime?.business_scoped && session.campusRuntime?.scheduling" mode="members" :college-id="scope.collegeId" :groups="scope.groups" :capabilities="scope.college.capabilities" :is-super="scope.isSuper" />
        <el-alert v-else title="组织成员业务尚未启用，组织与规则配置、已有学期资格仍可按权限维护。" type="info" :closable="false" />
      </template>
    </CampusWorkspace>
  </section>
</template>
