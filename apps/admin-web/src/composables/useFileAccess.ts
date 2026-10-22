import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { getFileAccess } from '../api/files'
import { createFileAccessCache } from '../utils/fileAccessCache'

/** 管理一个用户、一个材料面板的短期链接与异步回写。 */
export function useFileAccess(context: Ref<string>) {
  const urls = ref<Record<string, string>>({})
  const errors = ref<Record<string, string>>({})
  const retries = new Set<string>()
  const cache = createFileAccessCache(getFileAccess)
  let generation = 0

  function clear() {
    generation++
    cache.clear()
    urls.value = {}
    errors.value = {}
    retries.clear()
  }

  async function getUrl(id: string) {
    const current = generation
    try {
      const url = await cache.get(id)
      if (current !== generation) throw new Error('访问上下文已变化')
      urls.value[id] = url
      delete errors.value[id]
      return url
    } catch (e) {
      if (current === generation) errors.value[id] = e instanceof Error ? e.message : '图片读取失败'
      throw e
    }
  }

  function invalidate(id: string) {
    cache.invalidate(id)
    delete urls.value[id]
  }

  /** 链接失效自动换签一次；持续网络/权限失败留给用户手动重试，避免请求风暴。 */
  async function retry(id: string, manual = false) {
    if (!manual && retries.has(id)) {
      errors.value[id] = '图片加载失败，请点击重试'
      return
    }
    retries.add(id)
    const current = generation
    invalidate(id)
    try { await getUrl(id) }
    catch (e) {
      if (current === generation) errors.value[id] = e instanceof Error ? e.message : '图片加载失败'
    }
  }

  watch(context, clear, { flush: 'sync' })
  onBeforeUnmount(clear)
  return { urls, errors, getUrl, invalidate, retry }
}
