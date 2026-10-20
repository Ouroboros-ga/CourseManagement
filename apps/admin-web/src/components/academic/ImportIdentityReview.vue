<script setup lang="ts">
import AppPagination from '../../components/AppPagination.vue'
import { computed, ref, watch } from 'vue'
import { listScopedAcademic } from '../../api/scopedAcademic'
import { useSessionStore } from '../../stores/session'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { identityContext } from '../../utils/contextEpoch'
import SharedIdentity from '../campus/SharedIdentity.vue'
const session = useSessionStore(), page = ref(1), keyword = ref(''), selected = ref('')
const context = computed(() => `${identityContext(session.currentUser)}:${session.workspaceCollegeId}:${session.currentSemesterId}:${page.value}:${keyword.value}`)
const { data, error, load } = useWorkspaceRead(() => context.value, () => !!session.currentSemesterId, () => listScopedAcademic(session.workspaceCollegeId, 'teaching-classes', page.value, keyword.value, session.currentSemesterId))
watch(context, () => { selected.value = '' })
</script>
<template>
  <el-collapse><el-collapse-item title="导入后核对公共课教学班身份（可选，未关联仍可独立使用）" name="identity">
    <p>选择本学期需要核对的教学班，系统自动推荐时间地点等资料一致的候选。只有老师明确确认后才关联，不合并学院名单或考勤结果。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-input v-model.lazy="keyword" placeholder="按教学班名称搜索，回车查询" />
    <el-table :data="data?.items || []"><el-table-column prop="class_name" label="本院教学班" /><el-table-column prop="teacher_name" label="教师" /><el-table-column label="匹配候选"><template #default="{ row }"><el-button link @click="selected = row.id">查看系统推荐并核对</el-button></template></el-table-column></el-table>
    <AppPagination v-model:current-page="page" :total="data?.total || 0" :page-size="50" />
    <el-dialog :model-value="!!selected" title="确认共享教学班身份" width="850px" destroy-on-close :close-on-click-modal="false" @close="selected = ''"><SharedIdentity v-if="selected" :college-id="session.workspaceCollegeId" :teaching-id="selected" @changed="selected = ''; load()" /></el-dialog>
  </el-collapse-item></el-collapse>
</template>
