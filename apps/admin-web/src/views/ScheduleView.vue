<script setup lang="ts">
import TeachingSchedule from '../components/academic/TeachingSchedule.vue'
withDefaults(defineProps<{ mode?: 'legacy' | 'academic' | 'inspection'; openImport?: boolean; openSelfStudy?: boolean; importOnly?: boolean }>(), { mode: 'legacy', openImport: false, openSelfStudy: false, importOnly: false })
</script>
<template><TeachingSchedule :mode="mode" :open-import="openImport" :open-self-study="openSelfStudy" :import-only="importOnly" /></template>
