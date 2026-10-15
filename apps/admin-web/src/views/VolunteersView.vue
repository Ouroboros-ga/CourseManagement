<script setup lang="ts">
import StudentDirectory from '../components/students/StudentDirectory.vue'
withDefaults(defineProps<{ mode?: 'legacy' | 'students' | 'qualifications' }>(), { mode: 'legacy' })
</script>
<template><StudentDirectory :mode="mode" /></template>
