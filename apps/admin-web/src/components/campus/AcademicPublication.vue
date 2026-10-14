<script setup lang="ts">
import { onUnmounted, shallowRef, watch } from 'vue'
import { listScopedAcademic, type ScopedAcademicRow } from '../../api/scopedAcademic'
import { useAcademicPublication } from '../../composables/useAcademicPublication'
import { useSessionStore } from '../../stores/session'
import { ContextEpoch, identityContext } from '../../utils/contextEpoch'

const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()
const semesters = shallowRef<ScopedAcademicRow[]>([]), loadError = shallowRef('')
const state = useAcademicPublication(() => props.collegeId)
const { semesterId, previewResult, busy, error, message, preview, publish } = state
const epoch = new ContextEpoch(() => `${identityContext(session.currentUser)}:${props.collegeId}`)
watch(() => `${identityContext(session.currentUser)}:${props.collegeId}`, async () => {
  const cid = props.collegeId, ticket = epoch.begin()
  semesters.value = []; semesterId.value = ''; loadError.value = ''
  if (!cid) return
  try {
    let page = 1, rows: ScopedAcademicRow[] = []
    while (ticket.isCurrent()) {
      const response = await listScopedAcademic(cid, 'semesters', page, '')
      if (!ticket.isCurrent()) return
      rows = [...rows, ...response.items]
      if (rows.length >= response.total) break
      if (!response.items.length) throw new Error('学期分页发生变化，请刷新')
      page += 1
    }
    semesters.value = rows.filter(row => row.status === 'ACTIVE')
    semesterId.value = semesters.value[0]?.id || ''
  } catch (e) { if (ticket.isCurrent()) loadError.value = e instanceof Error ? e.message : '读取学期失败' }
}, { immediate: true })
onUnmounted(() => epoch.invalidate())
</script>

<template>
  <section>
    <p>发布本院正式课表供学生初始化个人副本。导入和编辑不会自动发布；再次发布仅展示更新通知，不覆盖已有个人课表。</p>
    <el-alert v-if="loadError || error" :title="loadError || error" type="error" :closable="false" />
    <el-alert v-if="message" :title="message" type="success" :closable="false" />
    <div class="publication-actions">
      <el-select v-model="semesterId" placeholder="选择学期" :disabled="busy" aria-label="发布学期">
        <el-option v-for="row in semesters" :key="row.id" :value="row.id" :label="String(row.name)" />
      </el-select>
      <el-button :disabled="!semesterId || busy" :loading="busy" @click="preview">预览发布</el-button>
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
