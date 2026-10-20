<script setup lang="ts">
import type { AdministratorAccount } from '../../api/administrators'
defineProps<{ rows: AdministratorAccount[]; busy: boolean }>()
const emit = defineEmits<{ reset: [row: AdministratorAccount]; update: [row: AdministratorAccount, operation: 'status' | 'platform'] }>()
</script>

<template>
  <el-table :data="rows" row-key="id">
    <el-table-column prop="username" label="账号" />
    <el-table-column prop="display_name" label="姓名" />
    <el-table-column label="身份"><template #default="{ row }"><el-tag>{{ row.can_manage_administrators ? '平台管理员' : '管理员' }}</el-tag></template></el-table-column>
    <el-table-column label="状态"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '启用' : '停用' }}</template></el-table-column>
    <el-table-column label="操作" min-width="340"><template #default="{ row }">
      <el-button link :disabled="busy" @click="emit('reset', row)">重置密码</el-button>
      <el-button link :disabled="busy" @click="emit('update', row, 'status')">{{ row.status === 'ACTIVE' ? '停用' : '启用' }}</el-button>
      <el-button link :disabled="busy" @click="emit('update', row, 'platform')">{{ row.can_manage_administrators ? '取消平台管理员' : '设为平台管理员' }}</el-button>
    </template></el-table-column>
  </el-table>
</template>
