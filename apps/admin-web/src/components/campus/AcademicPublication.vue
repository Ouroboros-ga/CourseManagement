<script setup lang="ts">
import { watch } from 'vue'
import { useAcademicPublication } from '../../composables/useAcademicPublication'
import { useSessionStore } from '../../stores/session'
import StudentTimetablePreview from './StudentTimetablePreview.vue'

const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()
const { semesterId, previewResult, busy, error, message, preview, publish } = useAcademicPublication(() => props.collegeId)
watch(() => session.currentSemesterId, value => { semesterId.value = value }, { immediate: true })
</script>

<template>
  <div class="academic-publication-container">
    <!-- 发布状态与操作栏 -->
    <div class="publication-header-card">
      <div class="header-intro">
        <h3>发布学期正式课表</h3>
        <p class="hint mt-1">
          发布本院正式课表供学生初始化小程序个人副本。导入与编辑不会自动发布；再次发布仅展示更新通知，不覆盖学生已有个人自选修改。
        </p>
      </div>

      <div v-if="error" class="mt-3">
        <el-alert :title="error" type="error" :closable="false" show-icon />
      </div>
      <div v-if="message" class="mt-3">
        <el-alert :title="message" type="success" :closable="false" show-icon />
      </div>

      <div class="publication-actions">
        <div class="flex items-center gap-2">
          <span class="text-xs font-semibold t-soft">当前学期：</span>
          <span class="badge badge-subtle font-mono text-xs">{{ session.currentSemesterName || '未选定学期' }}</span>
        </div>
        <el-button
          type="primary"
          :disabled="!semesterId || busy || session.currentSemester?.status === 'ARCHIVED'"
          :loading="busy"
          @click="preview"
        >
          预览发布诊断
        </el-button>
      </div>

      <!-- 预览诊断结果提示区 -->
      <transition name="el-zoom-in-top">
        <div v-if="previewResult" class="preview-result-panel info-box mt-4">
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div class="flex items-center gap-2">
                <span class="font-bold text-sm t-ink">{{ previewResult.semester_name }}</span>
                <span class="chip-blue font-mono">
                  当前已发布至第 {{ previewResult.current_version }} 版
                </span>
              </div>
              <div class="text-xs t-soft mt-1.5 flex items-center gap-4">
                <span>正式排课条目：<strong class="font-mono t-ink">{{ previewResult.schedule_count }}</strong> 条</span>
                <span>名单覆盖学生：<strong class="font-mono t-ink">{{ previewResult.student_count }}</strong> 人</span>
              </div>
              <div class="text-xs mt-2 font-medium" :class="previewResult.changed ? 't-amber' : 't-mute'">
                {{ previewResult.changed ? '● 本次内容较上一版有变动，确认后将发布并生成新版本通知。' : '○ 内容与当前线上版本一致，重复确认不会递增版本号或重复发送通知。' }}
              </div>
            </div>

            <div class="flex items-center gap-3">
              <el-button
                type="success"
                :loading="busy"
                :disabled="busy"
                @click="publish"
              >
                确认正式发布本学期课表
              </el-button>
            </div>
          </div>
        </div>
      </transition>
    </div>

    <!-- 高保真学生端课表预览视窗（支持切换行政班与周次） -->
    <StudentTimetablePreview
      :college-id="props.collegeId"
      :semester-id="semesterId"
    />
  </div>
</template>

<style scoped>
.academic-publication-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.publication-header-card {
  padding: 18px 20px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.publication-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.preview-result-panel {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.02);
}
</style>
