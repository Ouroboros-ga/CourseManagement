<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const generateLoading = ref(false)

function triggerRegenerate() {
  generateLoading.value = true
  setTimeout(() => {
    generateLoading.value = false
    ElMessage.success('成功同步生成新版本 Version 2.0！历史版本 Version 1.0 仍可查阅与下载。')
  }, 700)
}
</script>

<template>
  <div>
    <header class="page-head">
      <div class="crumb">
        <span>REPORT</span><em>●</em><span>第 4 周</span><em>●</em><span>版本归档</span>
      </div>
      <h1>学院考勤周报中心</h1>
      <p class="sub">
        周报版本不可物理篡改或覆盖，每次生成均永久归档并保留完整考勤汇总快照。
      </p>
    </header>

    <!-- 新鲜度警示横幅 -->
    <div class="banner">
      <div>
        <div class="b-title">周报源考勤数据已发生更新（behind_source: true）</div>
        <div class="b-desc">
          检测到本周有 1 笔异议考勤发生了有效终审改判，当前第 4 周周报（Version 1.0）已落后于最新考勤事实。
        </div>
      </div>
      <button class="btn btn-accent" style="flex-shrink: 0" :disabled="generateLoading" @click="triggerRegenerate">
        {{ generateLoading ? '正在生成…' : '重新生成 Version 2.0' }}
      </button>
    </div>

    <!-- 版本归档表 -->
    <div class="tbl-wrap">
      <div class="tbl-head">
        <div>
          <h3>第 4 周 · 历史归档</h3>
          <div class="meta">共 1 个版本，按生成时间倒序</div>
        </div>
        <button
          class="btn btn-sm"
          @click="ElMessage.info('正在流式生成 openpyxl XLSX 格式考勤周报下载链接...')"
        >
          下载最新 XLSX 周报
        </button>
      </div>

      <table class="tbl">
        <thead>
          <tr>
            <th>版本号</th>
            <th>生成时间戳</th>
            <th>操作人</th>
            <th>源修订号</th>
            <th>出勤率 / 缺勤率</th>
            <th>新鲜度状态</th>
            <th style="text-align: right">快照下载</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="cell-mono ver">Version 1.0</td>
            <td class="cell-mono cell-sub">2026-09-28 12:00:22</td>
            <td>
              <span class="cell-main">张老师</span>
              <span class="cell-sub role font-mono">TEACHER_ADMIN</span>
            </td>
            <td class="cell-mono cell-sub">rev_41</td>
            <td class="cell-mono">96.8% / 3.2%</td>
            <td><span class="tag tag-amber">已落后于考勤事实</span></td>
            <td style="text-align: right">
              <button class="btn btn-ghost btn-sm dl-json" @click="ElMessage.success('已开始下载快照 JSON')">JSON</button>
              <button class="btn btn-ghost btn-sm dl-xlsx" @click="ElMessage.success('已开始下载 XLSX 工作簿')">XLSX</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.banner { margin-bottom: 32px; }
.ver { font-weight: 600; }
.role { display: inline-block; margin-left: 8px; }
.dl-json { color: var(--blue); }
.dl-xlsx { color: var(--green); }
</style>
