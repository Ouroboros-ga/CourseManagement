/** 师生绑定码共用下载入口；凭证明文不进入持久化存储。 */
export function downloadExcel(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  try { link.click() } finally {
    link.remove()
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000)
  }
}
