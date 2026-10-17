<script setup lang="ts">
import TeachingSchedule from '../components/academic/TeachingSchedule.vue'
withDefaults(defineProps<{ mode?: 'legacy' | 'academic' | 'inspection'; openImport?: boolean; openSelfStudy?: boolean }>(), { mode: 'legacy', openImport: false, openSelfStudy: false })
</script>
<template><TeachingSchedule :mode="mode" :open-import="openImport" :open-self-study="openSelfStudy" /></template>
