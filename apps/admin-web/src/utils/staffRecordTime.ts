import { formatBeijingTime } from './datetime'

export function staffRecordTime(card: { starts_at?: string | null; ends_at?: string | null; inspection_date: string }): string {
  if (card.starts_at || card.ends_at) {
    return `${formatBeijingTime(card.starts_at, 'minute')} — ${formatBeijingTime(card.ends_at, 'minute')}`
  }
  return card.inspection_date
}
