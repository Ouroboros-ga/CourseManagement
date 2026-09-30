<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

interface MockOccurrence {
  id: string
  date: string
  period: string
  courseCode: string
  courseName: string
  teacher: string
  className: string
  studentCount: number
  location: string
  cluster: string
  statusText: string
  statusTag: 'gray' | 'green' | 'amber'
  selectable: boolean
  disabledReason?: string
}

const selectedIds = ref<string[]>(['occ-101', 'occ-102', 'occ-104'])
const dispatchLoading = ref(false)

const occurrences = reactive<MockOccurrence[]>([
  {
    id: 'occ-101',
    date: '09-28（周一）',
    period: '第 1-2 节 · 08:00-09:35',
    courseCode: 'CS201',
    courseName: '数据结构与算法',
    teacher: '陈教授',
    className: '计科2301-2302合班',
    studentCount: 68,
    location: '13号楼 302多媒体',
    cluster: '楼簇A（13/14/15号楼）',
    statusText: '待下发',
    statusTag: 'gray',
    selectable: true
  },
  {
    id: 'occ-102',
    date: '09-28（周一）',
    period: '第 3-4 节 · 10:00-11:35',
    courseCode: 'CS204',
    courseName: '操作系统原理',
    teacher: '王副教授',
    className: '软工2401班',
    studentCount: 34,
    location: '14号楼 205教室',
    cluster: '楼簇A（13/14/15号楼）',
    statusText: '待下发',
    statusTag: 'gray',
    selectable: true
  },
  {
    id: 'occ-103',
    date: '09-28（周一）',
    period: '第 5-6 节 · 14:00-15:35',
    courseCode: 'PE103',
    courseName: '大学体育(三) - 篮球',
    teacher: '赵教练',
    className: '计科2301班',
    studentCount: 32,
    location: '风雨操场篮球A区',
    cluster: '体育场地',
    statusText: '规则排除：体育课不可查',
    statusTag: 'amber',
    selectable: false,
    disabledReason: '根据系统排班规则，体育课不作为被查目标。'
  },
  {
    id: 'occ-104',
    date: '09-29（周二）',
    period: '第 1-2 节 · 08:00-09:35',
    courseCode: 'CS301',
    courseName: '计算机网络',
    teacher: '孙讲师',
    className: '计科2201-2202合班',
    studentCount: 72,
    location: '13号楼 108梯教',
    cluster: '楼簇A（13/14/15号楼）',
    statusText: '已排班：刘晨（志愿）',
    statusTag: 'green',
    selectable: true
  }
])

function toggleSelect(id: string) {
  const index = selectedIds.value.indexOf(id)
  if (index > -1) {
    selectedIds.value.splice(index, 1)
  } else {
    selectedIds.value.push(id)
  }
}

async function triggerDispatch() {
  if (selectedIds.value.length === 0) {
    ElMessage.warning('请至少选择一个待下发课次')
    return
  }

  dispatchLoading.value = true
  setTimeout(() => {
    dispatchLoading.value = false
    ElMessageBox.alert(
      `下发完成！<br/><br/>
      1. <b>任务生成</b>：成功生成 ${selectedIds.value.length} 个任务<br/>
      2. <b>自动排班</b>：已成功分配 2 个任务，未分配 1 个任务<br/>
      3. <b>未分配原因</b>：TASK-102 因候选人本班回避 (<code>SELF_CLASS_AVOID</code>) 无法排入，请在任务列表进行人工指定。`,
      '一键下发与排班结果',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '确定并查看任务'
      }
    )
  }, 800)
}
</script>

<template>
  <div>
    <header class="page-head">
      <div class="crumb">
        <span>第 4 周</span><em>●</em><span>09月28日 — 10月04日</span><em>●</em><span>名单已锁定 rev_9a3c</span>
      </div>
      <h1>课次勾选与下发</h1>
      <p class="sub">
        勾选需要查课的课次，系统将原子生成查课任务并自动调用排班求解器。已排除校历调休与体育课。
      </p>
      <div class="head-actions">
        <span class="sel-info">
          已选 <strong class="font-mono">{{ selectedIds.length }}</strong> / {{ occurrences.length }} 个课次
        </span>
        <button
          class="btn"
          @click="ElMessage.info('名单快照已基于学期当前有效学生名单生成，总人数无变动。')"
        >
          预览名单快照
        </button>
        <button class="btn btn-dark" :disabled="dispatchLoading" @click="triggerDispatch">
          {{ dispatchLoading ? '正在下发…' : '⚡ 一键下发并自动排班' }}
        </button>
      </div>
    </header>

    <div class="tbl-wrap">
      <!-- 筛选条 -->
      <div class="filter-bar">
        <div class="fgroup">
          <label>日期范围</label>
          <input type="date" class="input" value="2026-09-28" />
          <span class="muted">至</span>
          <input type="date" class="input" value="2026-09-30" />
        </div>
        <div class="fsep"></div>
        <div class="fgroup">
          <label>教学班</label>
          <select class="input">
            <option>全部教学班（本院 18 班级）</option>
            <option>计科2301-2302合班</option>
            <option>软工2401班</option>
          </select>
        </div>
        <div class="fsep"></div>
        <span class="tag tag-green">体育课自动排除已启用</span>
      </div>

      <!-- 课次表 -->
      <table class="tbl">
        <thead>
          <tr>
            <th style="width: 48px"></th>
            <th>课次时间</th>
            <th>课程信息</th>
            <th>教学班与规模</th>
            <th>上课地点</th>
            <th>排班状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in occurrences"
            :key="item.id"
            :class="{ 'row-disabled': !item.selectable }"
          >
            <td>
              <input
                type="checkbox"
                class="chk"
                :checked="selectedIds.includes(item.id)"
                :disabled="!item.selectable"
                @change="toggleSelect(item.id)"
              />
            </td>
            <td>
              <div class="cell-main">{{ item.date }}</div>
              <div class="cell-sub cell-mono">{{ item.period }}</div>
            </td>
            <td>
              <div class="cell-main">
                <span class="cell-mono code">{{ item.courseCode }}</span>
                {{ item.courseName }}
              </div>
              <div class="cell-sub">任课教师：{{ item.teacher }}</div>
            </td>
            <td>
              <div class="cell-main">{{ item.className }}</div>
              <div class="cell-sub">
                <span v-if="item.selectable" class="prog"><i style="width: 100%"></i></span>应到 {{ item.studentCount }} 人
              </div>
            </td>
            <td>
              <div class="cell-main">{{ item.location }}</div>
              <div class="cell-sub">{{ item.cluster }}</div>
            </td>
            <td>
              <span class="tag" :class="'tag-' + item.statusTag" :title="item.disabledReason">{{ item.statusText }}</span>
            </td>
            <td style="text-align: right">
              <span v-if="!item.selectable" class="cell-sub">系统排除</span>
              <button v-else class="btn btn-ghost btn-sm">详情</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.sel-info { font-size: 13px; color: var(--ink-mute); }
.sel-info strong { color: var(--ink); font-size: 15px; }

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  background: var(--paper-deep);
  border-bottom: 1px solid var(--line);
  font-size: 12px;
  flex-wrap: wrap;
}
.fgroup { display: flex; align-items: center; gap: 8px; }
.fgroup label { color: var(--ink-mute); font-weight: 500; }
.muted { color: var(--ink-mute); }
.fsep { width: 1px; height: 16px; background: var(--line-strong); }

.code { color: var(--blue); font-weight: 600; }
.row-disabled { opacity: 0.45; }
</style>
