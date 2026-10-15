<script setup lang="ts">
import TeachingSchedule from '../components/academic/TeachingSchedule.vue'
withDefaults(defineProps<{ mode?: 'legacy' | 'academic' | 'inspection'; openImport?: boolean }>(), { mode: 'legacy', openImport: false })
</script>
<template><TeachingSchedule :mode="mode" :open-import="openImport" /></template>
