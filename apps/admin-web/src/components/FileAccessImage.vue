<script setup lang="ts">
defineProps<{ src?: string; previewSrcList: string[]; fit?: 'cover' | 'contain'; error?: string }>()
const emit = defineEmits<{ failed: []; retry: [] }>()
</script>
<template>
  <div class="file-access-image">
    <el-image v-if="src" class="image-content" :src="src" :preview-src-list="previewSrcList" :fit="fit || 'contain'" @error="emit('failed')">
      <template #error><button type="button" class="image-retry" @click.stop="emit('retry')">{{ error || '图片加载失败，点击重试' }}</button></template>
    </el-image>
    <button v-else-if="error" type="button" class="image-retry" @click="emit('retry')">{{ error }} · 重试</button>
    <span v-else class="image-pending">图片读取中…</span>
  </div>
</template>
<style scoped>
.image-content { width:100%;height:100%; }
.image-retry { color:var(--ink-mute);background:var(--surface-2, #f5f5f5);border:1px solid var(--line, #ddd);padding:12px;cursor:pointer;max-width:100%;height:100%; }
.image-pending { display:inline-flex;align-items:center;justify-content:center;color:var(--ink-mute);font-size:12px; }
</style>
