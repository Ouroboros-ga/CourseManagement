<script setup lang="ts">
import { reactive } from 'vue'
import type { AdministratorCreate } from '../../api/administrators'
defineProps<{ busy: boolean }>()
const emit = defineEmits<{ submit: [body: AdministratorCreate]; cancel: [] }>()
const form = reactive<AdministratorCreate>({ username: '', display_name: '', initial_password: '', can_manage_administrators: false })
function submit() { emit('submit', { ...form, username: form.username.trim(), display_name: form.display_name.trim() }) }
</script>

<template>
  <el-form label-position="top" @submit.prevent="submit">
    <el-form-item label="账号"><el-input v-model="form.username" maxlength="64" autocomplete="off" /></el-form-item>
    <el-form-item label="姓名"><el-input v-model="form.display_name" maxlength="128" /></el-form-item>
    <el-form-item label="初始密码"><el-input v-model="form.initial_password" type="password" show-password autocomplete="new-password" maxlength="128" /></el-form-item>
    <el-form-item label="平台管理员"><el-switch v-model="form.can_manage_administrators" /></el-form-item>
    <p class="hint">开启后该账号可继续新增、停用其他超级管理员并重置其密码；不开启则只是普通超级管理员。两者的全校业务权限完全相同。</p>
    <el-button :disabled="busy" @click="emit('cancel')">取消</el-button>
    <el-button type="primary" native-type="submit" :loading="busy" :disabled="!form.username.trim() || !form.display_name.trim() || form.initial_password.length < 6">创建</el-button>
  </el-form>
</template>

<style scoped>
.hint { margin-bottom: 20px; color: var(--ink-mute); font-size: 13px; }
</style>
