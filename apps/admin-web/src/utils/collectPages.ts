/** Explicit full-snapshot operations only (detail reconciliation/export), never list loading. */
export async function collectPages<T extends { id: string }>(
  fetchPage: (page: number, pageSize: number) => Promise<{ items: T[]; total: number }>,
  current: () => boolean = () => true
): Promise<T[]> {
  const items: T[] = [], ids = new Set<string>()
  let expected: number | undefined
  for (let page = 1; ; page++) {
    if (!current()) return []
    const result = await fetchPage(page, 50)
    if (!current()) return []
    if (expected !== undefined && expected !== result.total) throw new Error('读取期间资料发生变化，请刷新重试')
    expected = result.total
    for (const item of result.items) {
      if (ids.has(item.id)) throw new Error('读取期间资料发生变化，请刷新重试')
      ids.add(item.id); items.push(item)
    }
    if (items.length >= expected) return items
    if (!result.items.length) throw new Error('资料分页不完整，请刷新重试')
  }
}
