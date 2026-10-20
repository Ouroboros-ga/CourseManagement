<script setup lang="ts">
import AppPagination from '../../components/AppPagination.vue'
import { computed, ref, watch } from 'vue'
import { useSessionStore } from '../../stores/session'
import { usePersonLinks } from '../../composables/usePersonLinks'
import type { PersonLinkKind, PersonLinkRow } from '../../api/importer'

const props = defineProps<{ collegeId: string; kind: PersonLinkKind }>()
const emit = defineEmits<{ saved: [] }>()
const session = useSessionStore()
const state = usePersonLinks(() => ({ cid: props.collegeId, kind: props.kind,
  semester: session.currentSemesterId || '', identity: JSON.stringify([session.currentUser?.id, session.workspace?.authorization_revision]) }))
const { plan, busy, error, saved, canConfirm, preview } = state
const page = ref(1)
watch(plan, () => { page.value = 1 })
const rows = computed(() => [...(plan.value?.pending || []), ...(plan.value?.links || [])])
const visible = computed(() => rows.value.slice((page.value - 1) * 50, page.value * 50))
const target = (row: PersonLinkRow) => row.class_name || row.class_code || ''
const status = (row: PersonLinkRow) => row.message || (row.action === 'CREATE' ? '确认后自动关联' : '已有关联，保持不变')
async function confirm() { if (await state.confirm()) emit('saved') }
</script>

<template>
  <section v-if="session.hasPermission('staff.manage')" class="person-links" aria-label="人员自动关联核对">
    <p>新导入的资料会自动匹配教职工档案。已有资料或后来补录的教职工，可在这里核对并补充关联。</p>
    <el-button :loading="busy" :disabled="kind === 'teaching' && !session.currentSemesterId" @click="preview">{{ kind === 'teaching' ? '核对本学期课表的教师关联' : '核对已有班主任与辅导员关联' }}</el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="saved" :title="saved" type="success" :closable="false" />
    <el-dialog :model-value="!!plan" title="核对人员关联" width="min(980px, 94vw)" @close="plan = null">
      <template v-if="plan">
        <p>可补关联 {{ plan.summary.person_links_create }} 条，已关联 {{ plan.summary.person_links_existing }} 条，待处理 {{ plan.summary.person_links_pending }} 条。</p>
        <p class="hint">只补充下方明确匹配的关系。同名请补工号；未找到人员请先导入教职工档案；已有不同责任人请使用交接。不会自动创建登录账号或修改历史任务。</p>
        <el-table :data="visible" empty-text="没有需要关联的人员资料">
          <el-table-column label="班级" min-width="160"><template #default="{ row }">{{ target(row) }}</template></el-table-column>
          <el-table-column label="职责" width="90"><template #default="{ row }">{{ row.kind === 'teaching' ? '任课教师' : row.duty === 'HEAD_TEACHER' ? '班主任' : '辅导员' }}</template></el-table-column>
          <el-table-column prop="name" label="姓名" width="100" /><el-table-column prop="staff_no" label="工号" width="110" />
          <el-table-column label="处理结果" min-width="240"><template #default="{ row }">{{ status(row) }}</template></el-table-column>
        </el-table>
        <AppPagination v-model:current-page="page" :page-size="50" :total="rows.length" />
      </template>
      <template #footer><el-button @click="plan = null">关闭</el-button><el-button type="primary" :loading="busy" :disabled="!canConfirm" @click="confirm">确认补充 {{ plan?.summary.person_links_create || 0 }} 条关联</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.person-links { padding: 16px; margin: 16px 0; border: 1px solid var(--line); }
.person-links p { margin-bottom: 12px; }.hint { color: var(--ink-mute); font-size: 13px; }
.el-alert,.el-pagination { margin-top: 12px; }
</style>
