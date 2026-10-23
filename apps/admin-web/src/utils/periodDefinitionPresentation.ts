type PeriodClock = { start_time?: string | null; end_time?: string | null }
const minutes = (value?: string | null) => {
  if (!value || !/^\d{2}:\d{2}(?::00)?$/.test(value)) return null
  const [h, m] = value.split(':').map(Number)
  return h! < 24 && m! < 60 ? h! * 60 + m! : null
}
export function periodDuration(row: PeriodClock): string {
  const start = minutes(row.start_time), end = minutes(row.end_time)
  return start !== null && end !== null && end > start ? `${end - start} 分钟` : '时间待核对'
}
export function periodSlotName(row: PeriodClock): string {
  const start = minutes(row.start_time)
  return start === null ? '未设置' : start < 12 * 60 ? '上午' : start < 18 * 60 ? '下午' : '晚间'
}
export function periodCoverage(rows: PeriodClock[]): string {
  const starts = rows.map(r => r.start_time?.slice(0, 5)).filter((v): v is string => !!v)
  const ends = rows.map(r => r.end_time?.slice(0, 5)).filter((v): v is string => !!v)
  return starts.length && ends.length ? `覆盖 ${starts.sort()[0]} 至 ${ends.sort().at(-1)} 教学作息` : ''
}
