<script setup lang="ts">
import { onErrorCaptured, ref, watch } from 'vue'
import { useCampusConfiguration } from '../../composables/useCampusConfiguration'
const state = useCampusConfiguration()
const { college, collegeId, groups, types, busy, error, can, isSuper, userId, reload, loadWorkspaces } = state
const renderError = ref('')
onErrorCaptured(reason => {
  renderError.value = reason instanceof Error ? reason.message : String(reason)
  return false
})
watch(collegeId, () => { renderError.value = '' })
</script>
<template>
  <section v-loading="busy">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-else-if="renderError" :title="`本页内容渲染失败：${renderError}`" type="error" show-icon>
      <p>切换页签或重新选择学院可重试；持续出现请把这条信息反馈给管理员。</p>
    </el-alert>
    <el-skeleton v-else-if="!college && busy" :rows="5" animated />
    <el-empty v-else-if="!college" description="暂无可用学院，请在顶部刷新权限或联系管理员" />
    <slot v-if="college && !renderError" :college="college" :college-id="collegeId" :groups="groups" :types="types"
      :can="can" :is-super="isSuper" :user-id="userId" :reload="reload" :refresh="loadWorkspaces" />
  </section>
</template>
