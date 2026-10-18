interface DropEntry {
  name: string; isFile: boolean; isDirectory: boolean
  file?: (success: (file: File) => void, failure: (error: DOMException) => void) => void
  createReader?: () => { readEntries: (success: (entries: DropEntry[]) => void, failure: (error: DOMException) => void) => void }
}

/** 必须在 drop 事件内调用：先同步捕获目录句柄，再异步读取全部分页。 */
export async function collectDroppedFiles(transfer: DataTransfer, maxFiles = 1000): Promise<File[]> {
  const fallback = Array.from(transfer.files || [])
  const roots = Array.from(transfer.items || []).filter(item => item.kind === 'file').map(item => ({
    entry: item.webkitGetAsEntry?.() as DropEntry | null,
    file: item.getAsFile?.()
  }))
  const found: File[] = []
  let scanned = 0
  async function visit(entry: DropEntry, prefix = '', depth = 0) {
    if (++scanned > 10000 || depth > 20) throw new Error('文件夹层级或目录项过多，请整理后再拖入')
    const path = prefix + entry.name
    if (entry.isFile && entry.file) {
      const file = await new Promise<File>((resolve, reject) => entry.file!(resolve, reject))
      if (found.length >= maxFiles) throw new Error(`每次最多拖入 ${maxFiles} 个文件，请分批处理`)
      Object.defineProperty(file, 'webkitRelativePath', { value: path, configurable: true })
      found.push(file)
    } else if (entry.isDirectory && entry.createReader) {
      const reader = entry.createReader()
      while (true) {
        const page = await new Promise<DropEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
        if (!page.length) break
        for (const child of page) await visit(child, path + '/', depth + 1)
      }
    }
  }
  if (roots.some(root => root.entry)) {
    for (const root of roots) {
      if (root.entry) await visit(root.entry)
      else if (root.file) found.push(root.file)
    }
  } else found.push(...fallback)
  if (found.length > maxFiles) throw new Error(`每次最多拖入 ${maxFiles} 个文件，请分批处理`)
  return found
}
