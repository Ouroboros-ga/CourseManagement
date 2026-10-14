import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { getFileAccess } from '../api/files'
import { createFileAccessCache } from '../utils/fileAccessCache'

/** 管理一个用户、一个材料面板的短期链接与异步回写。 */
export function useFileAccess(context: Ref<string>) {
  const urls = ref<Record<string, string>>({})
  const cache = createFileAccessCache(getFileAccess)
  let generation = 0

  function clear() {
    generation++
    cache.clear()
    urls.value = {}
  }

  async function getUrl(id: string) {
    const current = generation
    const url = await cache.get(id)
    if (current !== generation) throw new Error('访问上下文已变化')
    urls.value[id] = url
    return url
  }

  function invalidate(id: string) {
    cache.invalidate(id)
    delete urls.value[id]
  }

  watch(context, clear, { flush: 'sync' })
  onBeforeUnmount(clear)
  return { urls, getUrl, invalidate }
}
