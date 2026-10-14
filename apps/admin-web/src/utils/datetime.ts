export function formatBeijingTime(value?: string | null, style: 'full' | 'minute' | 'short' = 'full'): string {
  if (!value) return '-'
  const text = value.trim()
  // 校历日期不是 UTC 时刻；旧 API 的无偏移 datetime 则明确约定为 UTC。
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(text)) return '-'
  const iso = text.replace(' ', 'T') + (/(Z|[+-]\d{2}:?\d{2})$/i.test(text) ? '' : 'Z')
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '-'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  }).formatToParts(date)
  const get = (type: string) => parts.find(p => p.type === type)?.value || ''
  const result = `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`
  return style === 'short' ? result.slice(5, 16) : style === 'minute' ? result.slice(0, 16) : result
}
