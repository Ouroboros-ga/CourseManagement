<script setup lang="ts">
import { computed } from 'vue'
import { useSessionStore } from '../stores/session'
import { primaryPages, auxiliaryPages, canAccessPage } from '../navigation/workspaceNavigation'
const session = useSessionStore()
const entries = computed(() => [...primaryPages, ...auxiliaryPages].filter(row => canAccessPage(row.id, session)))
</script>
<template><section><h1>学院配置入口已调整</h1><p>教务、档案、组织和查课已迁入相应页面，当前学院及已选择学期继续保留。</p><ul><li v-for="row in entries" :key="row.id"><router-link :to="row.path">{{ row.label }}</router-link></li></ul></section></template>
