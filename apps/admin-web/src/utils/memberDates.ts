export function memberDates(semester?: { start_date: string; end_date?: string } | null) {
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
  const from = [today, semester?.start_date || today].sort().at(-1)!
  if (!semester?.end_date) return { from, to: '' }
  const end = new Date(`${semester.end_date}T00:00:00Z`)
  end.setUTCDate(end.getUTCDate() + 1)
  return { from, to: end.toISOString().slice(0, 10) }
}
