<script setup lang="ts" generic="T">
import { computed, ref, watch } from 'vue'
import AppPagination from './AppPagination.vue'

// Only bounded configuration/preview datasets use client-side rendering pages.
// Large business lists use API pagination and AppPagination directly.
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ data?: T[] }>(), { data: () => [] })
const page = ref(1)
const visible = computed(() => props.data.slice((page.value - 1) * 50, page.value * 50))
watch(() => props.data, () => { page.value = 1 })
watch(() => props.data.length, length => { page.value = Math.min(page.value, Math.max(1, Math.ceil(length / 50))) })
</script>

<template>
  <div class="paginated-table">
    <el-table v-bind="$attrs" :data="visible"><slot /></el-table>
    <AppPagination v-if="data.length > 50" v-model:current-page="page" :total="data.length" />
  </div>
</template>
