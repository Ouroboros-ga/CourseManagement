<script setup lang="ts">
import PaginatedTable from '../../components/PaginatedTable.vue'
import { computed } from 'vue'
import { campusActionLabels } from '../../api/campus'
import { myPermissionSources } from '../../api/organizationManagement'
import { useWorkspaceRead } from '../../composables/useWorkspaceRead'
import { useSessionStore } from '../../stores/session'
import { identityContext } from '../../utils/contextEpoch'
const props = defineProps<{ collegeId: string }>()
const session = useSessionStore()
const key = computed(() => `${identityContext(session.currentUser)}:${props.collegeId}:${session.workspace?.authorization_revision}`)
const { data, error } = useWorkspaceRead(() => key.value, () => !!props.collegeId && !!session.campusRuntime?.business_scoped, () => myPermissionSources(props.collegeId))
const labels: Record<string, string> = { FIXED_IDENTITY: '当前正式身份', GROUP_OWNER: '组织负责人专属授权', EXPLICIT_GRANT: '独立额外授权' }
</script>
<template>
  <el-collapse><el-collapse-item title="查看本人在当前学院的权限来源" name="sources"><el-alert v-if="error" :title="error" type="error" :closable="false" /><PaginatedTable :data="data || []"><el-table-column label="来源"><template #default="{ row }">{{ labels[row.kind] || row.kind }}</template></el-table-column><el-table-column label="范围"><template #default="{ row }">{{ row.scope.kind === 'COLLEGE' ? '本学院' : `指定资源 ${row.scope.ids.join('、')}` }}</template></el-table-column><el-table-column label="动作"><template #default="{ row }">{{ row.actions.map((x: string) => campusActionLabels[x] || x).join('、') }}</template></el-table-column></PaginatedTable></el-collapse-item></el-collapse>
</template>
