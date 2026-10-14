interface AccessLink {
  url: string
  expires_in: number
}

/** 仅存于当前页面内存；调用者在用户/材料上下文变化时 clear。 */
export function createFileAccessCache(
  fetchAccess: (id: string) => Promise<AccessLink>,
  now: () => number = Date.now
) {
  const links = new Map<string, { url: string; expires: number }>()
  const pending = new Map<string, Promise<string>>()
  let generation = 0

  function get(id: string): Promise<string> {
    const cached = links.get(id)
    if (cached && cached.expires > now()) return Promise.resolve(cached.url)
    const active = pending.get(id)
    if (active) return active
    const current = generation
    const started = now()
    const promise = fetchAccess(id).then(access => {
      if (current !== generation) throw new Error('访问上下文已变化')
      if (!access.url) throw new Error('未能获取文件访问链接')
      // 从请求开始计时，保守扣除传输耗时与五秒余量，不依赖服务器时钟。
      links.set(id, { url: access.url, expires: started + Math.max(0, access.expires_in - 5) * 1000 })
      return access.url
    }).finally(() => {
      if (pending.get(id) === promise) pending.delete(id)
    })
    pending.set(id, promise)
    return promise
  }

  function clear() {
    generation++
    links.clear()
    pending.clear()
  }

  function invalidate(id: string) {
    links.delete(id)
  }

  return { get, clear, invalidate }
}
