<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { memberImportApi } from '../../api/groupMembers'
import { useMemberImport } from '../../composables/useMemberImport'
import { useSessionStore } from '../../stores/session'
import { memberDates } from '../../utils/memberDates'

const props = defineProps<{ collegeId: string; groupId: string; semesterId: string }>()
const emit = defineEmits<{ changed: [] }>()
const session = useSessionStore()
const form = reactive({ ...memberDates(session.currentSemester), enable_qualification: session.hasPermission('volunteer.manage') })
const state = useMemberImport(() => ({ collegeId: props.collegeId, groupId: props.groupId, semesterId: props.semesterId,
  userId: session.currentUser?.id || '', allowed: session.hasPermission('volunteer.member.manage') }))
watch(() => JSON.stringify(form), state.invalidate)
const body = computed(() => ({ semester_id: props.semesterId, effective_from: form.from, effective_to: form.to, enable_qualification: form.enable_qualification }))
const valid = computed(() => !!form.from && !!form.to && form.from < form.to && session.currentSemester?.status === 'ACTIVE')
function choose(event: Event) { state.select((event.target as HTMLInputElement).files?.[0] || null) }
async function save() { if (await state.run(body.value, true)) { ElMessage.success('组成员与本学期资格已按预览保存'); emit('changed') } }
async function download() {
  const cid = props.collegeId, gid = props.groupId, uid = session.currentUser?.id
  try {
    const blob = await memberImportApi.template(cid, gid)
    if (cid !== props.collegeId || gid !== props.groupId || uid !== session.currentUser?.id) return
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url; anchor.download = '志愿者组成员模板.xlsx'; anchor.click(); URL.revokeObjectURL(url)
  } catch (e) { ElMessage.error(e instanceof Error ? e.message : '模板下载失败') }
}
</script>
<template>
  <section class="member-import">
    <p>先在“学生与班级”建立有效学籍，再导入当前组。模板只需学号、姓名；不创建学生、不自动改名，允许同一人加入多个组。</p>
    <el-button :disabled="state.busy.value" @click="download">下载 Excel 模板</el-button>
    <input :key="`${collegeId}:${groupId}:${semesterId}`" type="file" accept=".xlsx" aria-label="志愿者成员Excel" :disabled="state.busy.value" @change="choose">
    <p>每次最多200人、文件2MiB，仅支持单工作表xlsx；学号须为文本，保留前导零。</p>
    <el-form label-width="140px" :disabled="state.busy.value">
      <el-form-item label="成员生效日期"><el-date-picker v-model="form.from" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="失效日期（不含）"><el-date-picker v-model="form.to" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="本学期资格"><el-checkbox v-model="form.enable_qualification" :disabled="!session.hasPermission('volunteer.manage')">同时开通缺失/停用的本学期志愿者资格</el-checkbox></el-form-item>
    </el-form>
    <el-alert v-if="state.error.value" :title="state.error.value" type="error" :closable="false" />
    <el-alert v-if="state.result.value" :title="`新增 ${state.result.value.created} 人，已存在 ${state.result.value.unchanged} 人，开通资格 ${state.result.value.qualifications_enabled} 人。未自动排班。`" type="success" :closable="false" />
    <el-button :loading="state.busy.value" :disabled="!state.file.value || !valid" @click="state.run(body)">上传并核对</el-button>
    <template v-if="state.preview.value">
      <p>共 {{ state.preview.value.count }} 人；已存在 {{ state.preview.value.unchanged }} 人；需开通资格 {{ state.preview.value.qualifications_to_enable }} 人。</p>
      <el-alert v-if="!state.preview.value.can_commit" title="有阻断项，整批不会保存。请按行修正表格或先维护学籍，再重新上传。" type="error" :closable="false" />
      <el-table :data="state.preview.value.items" max-height="360">
        <el-table-column prop="source_row" label="表格行" width="80" /><el-table-column prop="student_no" label="学号" />
        <el-table-column prop="name" label="姓名" /><el-table-column label="处理结果"><template #default="{ row }">{{ row.status === 'ADD' ? '新增成员' : row.status === 'UNCHANGED' ? '已存在，保留' : '阻断' }}{{ row.qualification_action === 'ENABLE' ? ' · 开通本学期资格' : '' }}{{ row.message ? `：${row.message}` : '' }}</template></el-table-column>
      </el-table>
      <el-button type="primary" :loading="state.busy.value" :disabled="!state.preview.value.can_commit || !valid" @click="save">确认保存至当前组</el-button>
    </template>
  </section>
</template>
<style scoped>
.member-import { display: grid; gap: 14px; }
p { color: var(--ink-mute); line-height: 1.6; }
</style>
