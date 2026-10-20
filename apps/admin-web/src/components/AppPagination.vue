<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  currentPage?: number
  pageSize?: number
  total: number
}>(), { currentPage: 1, pageSize: 50 })
const emit = defineEmits<{ 'update:currentPage': [page: number]; 'current-change': [page: number] }>()
const start = computed(() => props.total ? (props.currentPage - 1) * props.pageSize + 1 : 0)
const end = computed(() => Math.min(props.currentPage * props.pageSize, props.total))
function change(page: number) { emit('update:currentPage', page); emit('current-change', page) }
</script>

<template>
  <footer class="app-pagination">
    <span class="range">显示第 {{ start }}—{{ end }} 条，共 {{ total }} 条 · {{ pageSize }} 条/页</span>
    <el-pagination :current-page="currentPage" :page-size="pageSize" :total="total"
      background layout="prev, pager, next, jumper" :pager-count="7" @current-change="change" />
  </footer>
</template>

<style scoped>
.app-pagination { display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:16px 12px;border-top:1px solid var(--line); }
.range { color:var(--ink-mute);font-size:13px; }
@media(max-width:700px) { .app-pagination { justify-content:center; }.app-pagination :deep(.el-pagination__jump) { display:none; } }
</style>
