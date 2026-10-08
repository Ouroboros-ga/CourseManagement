<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionStore } from '../stores/session'
import {
  listReports,
  listReportVersions,
  generateWeeklyReportVersion,
  getAttendanceStats,
  downloadReportVersionFile,
  type ReportSummaryItem,
  type ReportVersionSummary,
  type ReportVersionsResponse,
  type AttendanceStatsResponse
} from '../api/reports'

const sessionStore = useSessionStore()

const loading = ref(false)
const generateLoading = ref(false)
const downloadLoading = ref(false)

const selectedWeek = ref<number>(1)
const reportSummary = ref<ReportSummaryItem | null>(null)
const reportVersionsMeta = ref<ReportVersionsResponse | null>(null)
const reportVersions = ref<ReportVersionSummary[]>([])
const attendanceStats = ref<AttendanceStatsResponse | null>(null)

// 初始化周次
onMounted(() => {
  if (sessionStore.currentWeekNo) {
    selectedWeek.value = sessionStore.currentWeekNo
  }
  if (sessionStore.currentSemesterId) {
    fetchReportData()
  }
})

// 学期或周次切换时刷新
watch(
  () => [sessionStore.currentSemesterId, selectedWeek.value],
  ([semId]) => {
    if (semId) {
      fetchReportData()
    }
  }
)

async function fetchReportData() {
  if (!sessionStore.currentSemesterId) return
  loading.value = true
  try {
    const semId = Number(sessionStore.currentSemesterId)
    const week = selectedWeek.value

    // 1. 获取当周出勤统计口径
    try {
      const statsRes = await getAttendanceStats({ semester_id: semId, week_no: week })
      attendanceStats.value = statsRes
    } catch (e) {
      console.warn('获取考勤统计失败:', e)
      attendanceStats.value = null
    }

    // 2. 获取周报主条目
    const repRes = await listReports({ semester_id: semId, week_no: week, page_size: 1 })
    if (repRes.items && repRes.items.length > 0) {
      reportSummary.value = repRes.items[0]
      // 3. 获取版本列表
      const verRes = await listReportVersions(reportSummary.value.report_id)
      reportVersionsMeta.value = verRes
      reportVersions.value = verRes.items || []
    } else {
      reportSummary.value = null
      reportVersionsMeta.value = null
      reportVersions.value = []
    }
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '获取周报数据失败'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

// 是否需要生成新版本（源考勤有变动，或者尚未生成任何版本）
const isBehindSource = computed(() => {
  if (reportVersionsMeta.value) {
    return reportVersionsMeta.value.latest_behind_source
  }
  if (reportSummary.value) {
    return reportSummary.value.source_changed
  }
  return false
})

const nextVersionNo = computed(() => {
  if (reportVersionsMeta.value && reportVersionsMeta.value.latest_version_no) {
    return reportVersionsMeta.value.latest_version_no + 1
  }
  return 1
})

const latestPublishedVersion = computed(() => {
  return reportVersions.value.find(v => v.status === 'PUBLISHED') || null
})

// 触发生成新版本
async function triggerRegenerate() {
  if (!sessionStore.currentSemesterId) return
  try {
    let reason = ''
    if (reportVersions.value.length > 0) {
      const promptRes = await ElMessageBox.prompt(
        `确定要生成第 ${selectedWeek.value} 周周报 Version ${nextVersionNo.value}.0 吗？请输入生成说明（选填，入库审计）：`,
        '生成周报新版本',
        {
          confirmButtonText: '立即生成',
          cancelButtonText: '取消',
          inputValue: isBehindSource.value ? '源考勤数据更新后重新生成' : '例行发布考勤周报'
        }
      )
      reason = promptRes.value || ''
    }

    generateLoading.value = true
    const res = await generateWeeklyReportVersion({
      semester_id: Number(sessionStore.currentSemesterId),
      week_no: selectedWeek.value,
      scope: 'COLLEGE',
      reason: reason || undefined
    })

    ElMessage.success(`成功生成第 ${selectedWeek.value} 周考勤周报 Version ${res.version.version_no}.0！历史版本仍永久归档可查阅与下载。`)
    await fetchReportData()
  } catch (e) {
    // cancelled or error
  } finally {
    generateLoading.value = false
  }
}

// 下载周报文件（XLSX 或 JSON 快照）
async function handleDownload(versionId: string, kind: 'EXCEL' | 'SNAPSHOT') {
  downloadLoading.value = true
  try {
    const { blob, filename } = await downloadReportVersionFile(versionId, kind)
    const blobUrl = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(blobUrl)
    ElMessage.success(`周报文件【${filename}】已开始下载`)
  } catch (err: unknown) {
    const msg = err && typeof err === 'object' && 'message' in err ? String(err.message) : '下载失败'
    ElMessage.error(msg)
  } finally {
    downloadLoading.value = false
  }
}

// 下载最新周报
async function handleDownloadLatest() {
  if (!latestPublishedVersion.value) {
    ElMessage.warning('当前暂无可供下载的周报已发布版本，请先生成周报')
    return
  }
  await handleDownload(latestPublishedVersion.value.id, 'EXCEL')
}
</script>

<template>
  <div v-loading="loading">
    <header class="page-head">
      <div class="crumb font-mono">
        <span>REPORT</span>
        <em>●</em>
        <span>第 {{ selectedWeek }} 周</span>
        <em>●</em>
        <span>版本归档中心</span>
      </div>
      <div class="head-row">
        <div>
          <h1>学院考勤周报中心</h1>
          <p class="sub">
            周报版本不可物理篡改或覆盖，每次生成均永久归档并保留完整考勤汇总快照。终审改判或考勤事实更正后系统自动检测并提示重新生成。
          </p>
        </div>

        <!-- 顶部周次切换器 -->
        <div class="week-picker">
          <label class="wp-label font-mono">周次选择：</label>
          <select v-model="selectedWeek" class="wp-select font-mono">
            <option v-for="w in sessionStore.totalWeeks" :key="w" :value="w">
              第 {{ w }} 周
            </option>
          </select>
          <button class="btn btn-sm btn-ghost" @click="fetchReportData">⟳ 刷新</button>
        </div>
      </div>
    </header>

    <!-- 当周考勤事实聚合概览卡片 (真实统计) -->
    <div v-if="attendanceStats" class="stats-grid">
      <div class="stat-card">
        <div class="sc-label">已审核任务</div>
        <div class="sc-value font-mono">{{ attendanceStats.eligible_task_count }} <span class="sc-unit">堂</span></div>
        <div class="sc-sub cell-sub">已通过且未取消任务</div>
      </div>
      <div class="stat-card">
        <div class="sc-label">应到总人次</div>
        <div class="sc-value font-mono">{{ attendanceStats.overall.expected_count }} <span class="sc-unit">人次</span></div>
        <div class="sc-sub cell-sub">计入统计的有效分母</div>
      </div>
      <div class="stat-card">
        <div class="sc-label">正常出勤人次</div>
        <div class="sc-value font-mono text-green">{{ attendanceStats.overall.normal_count }} <span class="sc-unit">人次</span></div>
        <div class="sc-sub cell-sub">清点正常或改判正常</div>
      </div>
      <div class="stat-card">
        <div class="sc-label">请假 / 迟到 / 旷课</div>
        <div class="sc-value font-mono text-amber">
          {{ attendanceStats.overall.leave_count }} / {{ attendanceStats.overall.late_count }} / {{ attendanceStats.overall.absent_count }}
        </div>
        <div class="sc-sub cell-sub">异常人次分类汇总</div>
      </div>
      <div class="stat-card highlight">
        <div class="sc-label">全院综合到课率</div>
        <div class="sc-value font-mono text-accent">
          {{
            attendanceStats.overall.statistics_available && attendanceStats.overall.expected_count > 0
              ? (((attendanceStats.overall.normal_count) / attendanceStats.overall.expected_count) * 100).toFixed(1) + '%'
              : '暂无'
          }}
        </div>
        <div class="sc-sub cell-sub">
          异常率: {{ attendanceStats.overall.abnormal_rate != null ? (attendanceStats.overall.abnormal_rate * 100).toFixed(1) + '%' : '-' }}
        </div>
      </div>
    </div>

    <!-- 新鲜度警示横幅：当周报尚未生成或源考勤已更新时展示 -->
    <div v-if="reportVersions.length === 0" class="banner banner-empty">
      <div>
        <div class="b-title">第 {{ selectedWeek }} 周尚未生成周报归档版本</div>
        <div class="b-desc">
          当前学期第 {{ selectedWeek }} 周已有 {{ attendanceStats?.eligible_task_count || 0 }} 堂查课任务完成审核，可随时生成初始版本 Version 1.0 工作簿与快照。
        </div>
      </div>
      <button
        class="btn btn-accent"
        style="flex-shrink: 0"
        :disabled="generateLoading"
        @click="triggerRegenerate"
      >
        {{ generateLoading ? '正在生成…' : '生成 Version 1.0 周报' }}
      </button>
    </div>

    <div v-else-if="isBehindSource" class="banner banner-warn">
      <div>
        <div class="b-title">周报源考勤数据已发生更新（behind_source: true）</div>
        <div class="b-desc">
          检测到本周考勤数据发生变动（存在新审核提交或考勤异议终审改判），当前最新周报（Version {{ reportVersionsMeta?.latest_version_no }}.0）已落后于最新考勤事实。
        </div>
      </div>
      <button
        class="btn btn-accent"
        style="flex-shrink: 0"
        :disabled="generateLoading"
        @click="triggerRegenerate"
      >
        {{ generateLoading ? '正在生成…' : `重新生成 Version ${nextVersionNo}.0` }}
      </button>
    </div>

    <div v-else class="banner banner-ok">
      <div>
        <div class="b-title text-green">第 {{ selectedWeek }} 周周报为最新考勤事实（已归档）</div>
        <div class="b-desc">
          当前归档版本与考勤库源修订号（rev_{{ reportVersionsMeta?.current_source_revision }}）保持一致，各班级考勤比例完全对齐。
        </div>
      </div>
      <button
        class="btn btn-ghost"
        style="flex-shrink: 0"
        :disabled="generateLoading"
        @click="triggerRegenerate"
      >
        {{ generateLoading ? '正在生成…' : `再次生成新版本 (Version ${nextVersionNo}.0)` }}
      </button>
    </div>

    <!-- 版本归档表 -->
    <div class="panel">
      <div class="panel-head">
        <div>
          <h3 class="panel-title font-serif">版本归档历史</h3>
          <div class="cell-sub">
            第 {{ selectedWeek }} 周已归档 {{ reportVersions.length }} 个版本，按生成时间倒序排列
          </div>
        </div>
        <button
          class="btn btn-sm btn-dark"
          :disabled="!latestPublishedVersion || downloadLoading"
          @click="handleDownloadLatest"
        >
          ⬇ 下载最新 XLSX 周报
        </button>
      </div>

      <div v-if="reportVersions.length === 0" class="empty-text cell-sub">
        暂无版本记录，请点击上方按钮生成初始周报。
      </div>

      <table v-else class="tbl">
        <thead>
          <tr>
            <th>版本号</th>
            <th>生成时间</th>
            <th>操作人</th>
            <th>源修订号</th>
            <th>状态</th>
            <th>新鲜度状态</th>
            <th>生成事由</th>
            <th style="text-align: right">下载产物</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ver in reportVersions" :key="ver.id">
            <td class="cell-mono ver">
              Version {{ ver.version_no }}.0
            </td>
            <td class="cell-mono cell-sub">
              {{ ver.generated_at ? ver.generated_at.substring(0, 19).replace('T', ' ') : ver.created_at.substring(0, 19).replace('T', ' ') }}
            </td>
            <td>
              <span class="cell-main">{{ ver.generated_by ? '用户 #' + ver.generated_by : '管理员' }}</span>
              <span class="cell-sub role font-mono">ADMIN</span>
            </td>
            <td class="cell-mono cell-sub">rev_{{ ver.source_revision }}</td>
            <td>
              <span
                class="tag"
                :class="{
                  'tag-green': ver.status === 'PUBLISHED',
                  'tag-amber': ver.status === 'GENERATING',
                  'tag-red': ver.status === 'FAILED'
                }"
              >
                {{ ver.status === 'PUBLISHED' ? '已发布' : (ver.status === 'GENERATING' ? '生成中' : '失败') }}
              </span>
            </td>
            <td>
              <span v-if="ver.behind_source" class="tag tag-amber">已落后于考勤事实</span>
              <span v-else class="tag tag-green">最新有效快照</span>
            </td>
            <td class="cell-sub" style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ ver.reason || '例行生成' }}
            </td>
            <td style="text-align: right">
              <button
                class="btn btn-ghost btn-sm dl-json"
                :disabled="!ver.snapshot_available || downloadLoading"
                @click="handleDownload(ver.id, 'SNAPSHOT')"
              >
                JSON 快照
              </button>
              <button
                class="btn btn-ghost btn-sm dl-xlsx"
                :disabled="!ver.excel_available || downloadLoading"
                @click="handleDownload(ver.id, 'EXCEL')"
              >
                XLSX 表格
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.page-head { margin-bottom: 24px; }
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}
.crumb em { margin: 0 8px; color: var(--ink-mute); }

.week-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--paper-deep);
  padding: 8px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--line);
}
.wp-label { font-size: 12px; color: var(--ink-soft); }
.wp-select {
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid var(--line-strong);
  background: var(--paper);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

/* 考勤事实指标栅格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.stat-card {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 16px 18px;
}
.stat-card.highlight {
  background: #fdfbf7;
  border-color: var(--ink);
}
.sc-label { font-size: 12px; color: var(--ink-soft); font-weight: 500; margin-bottom: 8px; }
.sc-value { font-size: 22px; font-weight: 700; color: var(--ink); line-height: 1.1; margin-bottom: 4px; }
.sc-unit { font-size: 12px; font-weight: normal; color: var(--ink-mute); }
.sc-sub { font-size: 11px; }

/* 警示横幅 */
.banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px 24px;
  border-radius: var(--radius);
  margin-bottom: 24px;
  gap: 20px;
  flex-wrap: wrap;
}
.banner-empty {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
}
.banner-warn {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-left: 4px solid var(--accent);
}
.banner-ok {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-left: 4px solid var(--green);
}
.b-title { font-size: 15px; font-weight: 700; margin-bottom: 4px; }
.b-desc { font-size: 13px; color: var(--ink-soft); line-height: 1.5; }

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}
.ver { font-weight: 600; }
.role { display: inline-block; margin-left: 8px; }
.dl-json { color: var(--blue); }
.dl-xlsx { color: var(--green); font-weight: 600; }
.empty-text { padding: 32px 0; text-align: center; }

.text-green { color: var(--green); }
.text-amber { color: #d97706; }
.text-accent { color: var(--accent); }

@media (max-width: 1024px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .stats-grid { grid-template-columns: 1fr; }
}
</style>
