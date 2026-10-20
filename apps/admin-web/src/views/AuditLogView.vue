<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, ref } from 'vue'
import {
  AUDIT_WINDOW_MAX_DAYS, auditLogDetail, auditWindowDays, listAuditLogs,
  type AuditLogDetail, type AuditLogRow
} from '../api/auditLogs'
import { useSessionStore } from '../stores/session'
import { ContextEpoch } from '../utils/contextEpoch'
import { AUDIT_ACTION_CODES, AUDIT_RESOURCE_TYPES, describeAuditAction, describeAuditResource } from '../utils/auditActions'
import { formatBeijingTime } from '../utils/datetime'

const session = useSessionStore()
const epoch = new ContextEpoch(() => session.currentUser?.id || '')

// 查询窗口按北京日界解释，与日志时间列的显示口径保持一致。
function beijingDay(offsetDays: number): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date(Date.now() + offsetDays * 86400000))
  const get = (type: string) => parts.find(part => part.type === type)?.value || ''
  return `${get('year')}-${get('month')}-${get('day')}`
}

const range = ref<[string, string] | null>([beijingDay(-6), beijingDay(0)])
const action = ref(''), resourceType = ref(''), resourceId = ref('')
const rows = shallowRef<AuditLogRow[]>([]), total = ref(0), page = ref(1)
const busy = ref(false), error = ref(''), notice = ref('')
const detail = shallowRef<AuditLogDetail | null>(null), detailVisible = ref(false), detailBusy = ref(false)
const actionOptions = computed(() => AUDIT_ACTION_CODES.map(code => ({ value: code, label: describeAuditAction(code) })))
const resourceOptions = computed(() => AUDIT_RESOURCE_TYPES.map(type => ({ value: type, label: describeAuditResource(type) })))
const actorLabel = (row: AuditLogRow) => row.actor_name
  ? `${row.actor_name}${row.actor_username ? `（${row.actor_username}）` : ''}`
  : '已注销账号'

async function search(target = 1) {
  const window = range.value
  if (!window || !window[0] || !window[1]) { notice.value = '请先选择查询日期范围'; rows.value = []; total.value = 0; return }
  if (window[1] < window[0]) { notice.value = '结束日期不得早于开始日期'; return }
  if (auditWindowDays(window[0], window[1]) > AUDIT_WINDOW_MAX_DAYS) {
    notice.value = `单次查询最多覆盖 ${AUDIT_WINDOW_MAX_DAYS} 天，请缩小日期范围`
    return
  }
  notice.value = ''
  const ticket = epoch.begin()
  busy.value = true; error.value = ''; page.value = target
  try {
    const result = await listAuditLogs({
      from: window[0], to: window[1], action: action.value || undefined,
      resourceType: resourceType.value || undefined, resourceId: resourceId.value || undefined, page: target
    })
    if (!ticket.isCurrent()) return
    rows.value = result.items; total.value = result.total
  } catch (e) {
    if (ticket.isCurrent()) { rows.value = []; total.value = 0; error.value = e instanceof Error ? e.message : '日志读取失败' }
  } finally { if (ticket.isLatest()) busy.value = false }
}

async function openDetail(row: AuditLogRow) {
  if (detailBusy.value) return
  const ticket = epoch.begin()
  detailBusy.value = true; detail.value = null; detailVisible.value = true
  try {
    const result = await auditLogDetail(row.id)
    if (ticket.isCurrent()) detail.value = result
  } catch (e) { if (ticket.isCurrent()) error.value = e instanceof Error ? e.message : '详情读取失败' }
  finally { if (ticket.isLatest()) detailBusy.value = false }
}

function changes(row: AuditLogDetail) {
  const keys = [...new Set([...Object.keys(row.before || {}), ...Object.keys(row.after || {})])]
  return keys.map(key => ({
    key,
    before: JSON.stringify((row.before || {})[key] ?? null),
    after: JSON.stringify((row.after || {})[key] ?? null)
  }))
}

onMounted(() => { void search() })
onUnmounted(() => epoch.invalidate())
</script>

<template>
  <section>
    <header class="page-head">
      <h1>操作日志</h1>
      <p class="sub">记录管理端每一次写入操作的操作者、时间和对象，仅超级管理员与平台管理员可查。日志只追加，不能修改或删除。</p>
    </header>
    <el-alert v-if="notice" :title="notice" type="warning" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div class="filter-bar">
      <el-date-picker
        v-model="range" type="daterange" value-format="YYYY-MM-DD" unlink-panels
        start-placeholder="开始日期" end-placeholder="结束日期" :disabled="busy"
      />
      <el-select v-model="action" filterable clearable allow-create default-first-option placeholder="动作（可手输）" :disabled="busy">
        <el-option v-for="row in actionOptions" :key="row.value" :value="row.value" :label="`${row.label}　${row.value}`" />
      </el-select>
      <el-select v-model="resourceType" filterable clearable placeholder="对象类型" :disabled="busy">
        <el-option v-for="row in resourceOptions" :key="row.value" :value="row.value" :label="`${describeAuditResource(row.value)}　${row.value}`" />
      </el-select>
      <el-input v-model="resourceId" placeholder="对象 ID" clearable :disabled="busy" class="filter-id" />
      <el-button type="primary" :loading="busy" @click="search(1)">查询</el-button>
    </div>
    <el-table v-loading="busy" :data="rows" row-key="id" empty-text="所选范围内没有操作记录">
      <el-table-column label="时间" width="180">
        <template #default="{ row }"><span class="mono">{{ formatBeijingTime(row.created_at) }}</span></template>
      </el-table-column>
      <el-table-column label="操作者" min-width="150">
        <template #default="{ row }">{{ actorLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="动作" min-width="220">
        <template #default="{ row }">
          <div>{{ describeAuditAction(row.action) }}</div>
          <div class="code">{{ row.action }}</div>
        </template>
      </el-table-column>
      <el-table-column label="对象" min-width="200">
        <template #default="{ row }">
          <div>{{ describeAuditResource(row.resource_type) }}</div>
          <div class="code">{{ row.resource_id || '—' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="详情" width="90">
        <template #default="{ row }"><el-button link :disabled="busy" @click="openDetail(row)">查看</el-button></template>
      </el-table-column>
    </el-table>
    <el-pagination
      :current-page="page" :page-size="50" :total="total" layout="prev, pager, next, total"
      :disabled="busy" @current-change="search"
    />

    <el-drawer v-model="detailVisible" title="操作详情" size="480px">
      <p v-if="detailBusy">正在读取…</p>
      <template v-else-if="detail">
        <dl class="detail-list">
          <dt>时间</dt><dd class="mono">{{ formatBeijingTime(detail.created_at) }}</dd>
          <dt>操作者</dt><dd>{{ actorLabel(detail) }}</dd>
          <dt>动作</dt><dd>{{ describeAuditAction(detail.action) }}<div class="code">{{ detail.action }}</div></dd>
          <dt>对象</dt><dd>{{ describeAuditResource(detail.resource_type) }}<div class="code">{{ detail.resource_id || '—' }}</div></dd>
          <dt>说明</dt><dd>{{ detail.reason || '未填写' }}</dd>
          <dt>请求号</dt><dd class="code">{{ detail.request_id || '—' }}</dd>
        </dl>
        <h4>字段变化</h4>
        <p v-if="!changes(detail).length" class="muted">该动作未记录字段级前后值。</p>
        <el-table v-else :data="changes(detail)" size="small">
          <el-table-column prop="key" label="字段" width="150" />
          <el-table-column prop="before" label="变更前" />
          <el-table-column prop="after" label="变更后" />
        </el-table>
        <p class="muted">仅保留业务关键字段；名单、证明材料等整包内容不进入日志。</p>
      </template>
    </el-drawer>
  </section>
</template>

<style scoped>
.filter-bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin: 16px 0; }
.filter-bar .el-select { width: 260px; }
.filter-id { width: 180px; }
.mono { font-family: var(--font-mono, 'IBM Plex Mono', monospace); }
.code { font-size: 11px; color: var(--ink-mute); font-family: var(--font-mono, 'IBM Plex Mono', monospace); }
.muted { font-size: 12px; color: var(--ink-mute); }
.detail-list { display: grid; grid-template-columns: 72px 1fr; gap: 6px 12px; margin: 0 0 20px; }
.detail-list dt { color: var(--ink-mute); font-size: 12px; }
.detail-list dd { margin: 0; }
h4 { margin: 0 0 8px; }
</style>
