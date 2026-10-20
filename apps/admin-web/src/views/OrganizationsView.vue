<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'
import CampusWorkspace from '../components/workspace/CampusWorkspace.vue'
import GroupManager from '../components/campus/GroupManager.vue'
import VolunteersView from './VolunteersView.vue'
const session = useSessionStore(), route = useRoute(), router = useRouter()
const directory = computed(() => session.hasPermission('volunteer.read') && (route.query.tab === 'qualifications' || !session.hasPermission('volunteer.group.read')))
function showGroups() { void router.push({ query: { ...route.query, tab: 'groups', group_id: undefined, panel: undefined } }) }
</script>
<template>
  <section>
    <header class="page-head">
      <div><h1>{{ directory ? '全部志愿者' : '志愿者组织' }}</h1><p class="sub">{{ directory ? '查看本学期志愿者及所属组织。' : '先选一个组织，在组织内管理成员、设置查课范围，再前往查课安排。' }}</p></div>
      <el-button v-if="directory && session.hasPermission('volunteer.group.read')" @click="showGroups">返回组织列表</el-button>
    </header>
    <VolunteersView v-if="directory" mode="qualifications" />
    <CampusWorkspace v-else-if="session.hasPermission('volunteer.group.read')" v-slot="scope">
      <GroupManager :key="`${scope.userId}:${scope.collegeId}:${scope.college.authorization_revision}`" :college-id="scope.collegeId" :rows="scope.groups" :types="scope.types" :user-id="scope.userId" :can-manage="scope.can('volunteer.group.manage')" :can-publish="scope.can('volunteer.config.publish')" :capabilities="scope.college.capabilities" @changed="scope.reload" />
    </CampusWorkspace>
    <el-empty v-else description="暂无组织查看权限；请联系学院管理员确认权限范围。" />
  </section>
</template>
<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
</style>
