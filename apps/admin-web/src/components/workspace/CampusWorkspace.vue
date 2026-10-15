<script setup lang="ts">
import { useCampusConfiguration } from '../../composables/useCampusConfiguration'
const state = useCampusConfiguration()
const { college, collegeId, groups, types, busy, error, can, isSuper, userId, reload, loadWorkspaces } = state
</script>
<template>
  <section v-loading="busy">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-empty v-else-if="!college && !busy" description="暂无可用学院，请在顶部刷新权限或联系管理员" />
    <slot v-if="college" :college="college" :college-id="collegeId" :groups="groups" :types="types"
      :can="can" :is-super="isSuper" :user-id="userId" :reload="reload" :refresh="loadWorkspaces" />
  </section>
</template>
