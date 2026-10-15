<script setup lang="ts">
import { watch } from 'vue'
import { useAcademicPublication } from '../../composables/useAcademicPublication'
import { useSessionStore } from '../../stores/session'
const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()
const { semesterId, previewResult, busy, error, message, preview, publish } = useAcademicPublication(() => props.collegeId)
watch(() => session.currentSemesterId, value => { semesterId.value = value }, { immediate: true })
</script>

<template>
  <section>
    <p>发布本院正式课表供学生初始化个人副本。导入和编辑不会自动发布；再次发布仅展示更新通知，不覆盖已有个人课表。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <div class="publication-actions">
      <span>发布学期：{{ session.currentSemesterName }}</span>
      <el-button :disabled="!semesterId || busy || session.currentSemester?.status === 'ARCHIVED'" :loading="busy" @click="preview">预览发布</el-button>
    </div>
    <div v-if="previewResult">
      <p>{{ previewResult.semester_name }}：{{ previewResult.schedule_count }} 条课表，{{ previewResult.student_count }} 名正式名单学生；当前第 {{ previewResult.current_version }} 版。</p>
      <p>{{ previewResult.changed ? '本次内容有变化，确认后发布新版本。' : '内容没有变化，重复确认不会产生新版本或重复通知。' }}</p>
      <el-button type="primary" :loading="busy" :disabled="busy" @click="publish">确认发布本学期课表</el-button>
    </div>
  </section>
</template>

<style scoped>
.publication-actions { display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }
</style>
