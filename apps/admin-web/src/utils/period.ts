/**
 * 高校标准节次与时段换算规范
 * 
 * 高校教务规则：全天划分为 1-11 小节，每两小节为一次正常课程时间（大节 1-6）：
 * - 大节 1 -> 第 1-2 节 (08:00 - 09:35, 上午一)
 * - 大节 2 -> 第 3-4 节 (10:05 - 11:40, 上午二)
 * - 大节 3 -> 第 5-6 节 (13:30 - 15:05, 下午一)
 * - 大节 4 -> 第 7-8 节 (15:25 - 17:00, 下午二)
 * - 大节 5 -> 第 9-10 节 (18:30 - 20:05, 晚上一)
 * - 大节 6 -> 第 11 节 (20:15 - 21:50, 晚上二)
 */

export interface PeriodSlotInfo {
  slot: number
  sectionStart: number
  sectionEnd: number
  sectionLabel: string // 如 "第 1-2 节"
  timeRange: string    // 如 "08:00 - 09:35"
  name: string         // 如 "上午一"
}

export const STANDARD_PERIOD_SLOTS: Record<number, PeriodSlotInfo> = {
  1: { slot: 1, sectionStart: 1, sectionEnd: 2, sectionLabel: '第 1-2 节', timeRange: '08:00 - 09:35', name: '上午一' },
  2: { slot: 2, sectionStart: 3, sectionEnd: 4, sectionLabel: '第 3-4 节', timeRange: '10:05 - 11:40', name: '上午二' },
  3: { slot: 3, sectionStart: 5, sectionEnd: 6, sectionLabel: '第 5-6 节', timeRange: '13:30 - 15:05', name: '下午一' },
  4: { slot: 4, sectionStart: 7, sectionEnd: 8, sectionLabel: '第 7-8 节', timeRange: '15:25 - 17:00', name: '下午二' },
  5: { slot: 5, sectionStart: 10, sectionEnd: 11, sectionLabel: '第 10-11 节', timeRange: '18:30 - 20:50', name: '晚上课' },
  6: { slot: 6, sectionStart: 10, sectionEnd: 11, sectionLabel: '第 10-11 节', timeRange: '18:30 - 20:50', name: '晚上课' },
}

export const PERIOD_PRESET_OPTIONS = [
  { value: 1, label: '第 1-2 节' },
  { value: 2, label: '第 3-4 节' },
  { value: 3, label: '第 5-6 节' },
  { value: 4, label: '第 7-8 节' },
  { value: 5, label: '第 10-11 节' },
]

/**
 * 格式化节次展示（纯节次，不标注具体时间，符合高校规范）
 * @param start 开始大节（或小节）
 * @param end 结束大节（或小节）
 */
export function formatPeriodText(
  start?: number | null,
  end?: number | null,
  _withTime: boolean = false
): string {
  if (start == null && end == null) return '—'
  const s = start ?? end ?? 1
  const e = end ?? start ?? 1

  // 特殊情况：兼容老数据中 10-11 节跨 5..6 或单 6 的情况
  if ((s === 5 && e === 6) || (s === 6 && e === 6) || (s === 10 && e === 11) || (s === 9 && e === 11)) {
    return '第 10-11 节'
  }

  // 情况 1：如果传入的是系统标准大节编号（1..6）
  if (s >= 1 && s <= 6 && e >= 1 && e <= 6) {
    const sInfo = STANDARD_PERIOD_SLOTS[s]
    const eInfo = STANDARD_PERIOD_SLOTS[e]
    if (s === e) {
      return sInfo ? sInfo.sectionLabel : `第 ${s} 节`
    }
    // 跨多个大节（如实验课或连排）
    const secStart = sInfo?.sectionStart ?? s
    const secEnd = eInfo?.sectionEnd ?? e
    return secStart === secEnd ? `第 ${secStart} 节` : `第 ${secStart}-${secEnd} 节`
  }

  // 情况 2：若传入的数据已是直接的小节编号（如 1..12）
  if (s === e) {
    return `第 ${s} 节`
  }
  return `第 ${s}-${e} 节`
}

/**
 * 仅获取节次对应的时间范围（例如 "08:00 - 09:35"）
 */
export function getPeriodTimeRange(start?: number | null, end?: number | null): string {
  if (start == null && end == null) return ''
  const s = start ?? end ?? 1
  const e = end ?? start ?? 1
  if (s >= 1 && s <= 6 && e >= 1 && e <= 6) {
    const sInfo = STANDARD_PERIOD_SLOTS[s]
    const eInfo = STANDARD_PERIOD_SLOTS[e]
    if (s === e && sInfo) return sInfo.timeRange
    if (sInfo && eInfo) {
      return `${sInfo.timeRange.split(' - ')[0]} - ${eInfo.timeRange.split(' - ')[1]}`
    }
  }
  return ''
}
