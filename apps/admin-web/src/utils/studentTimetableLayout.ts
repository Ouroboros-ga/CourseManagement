/**
 * 学生端课表高保真预览与排课布局引擎
 * 对齐微信小程序端最新课程表算法与视觉规范 (MORANDI_PALETTE + 区间聚类分栏)
 */

export interface MorandiColor {
  bg: string
  text: string
  border: string
}

export const MORANDI_PALETTE: MorandiColor[] = [
  { bg: '#EBF3FE', text: '#1E40AF', border: '#BFDBFE' }, // 经典雾蓝
  { bg: '#F0FDF4', text: '#166534', border: '#BBF7D0' }, // 浅草绿
  { bg: '#FEF3C7', text: '#92400E', border: '#FDE68A' }, // 暖米杏
  { bg: '#F5F3FF', text: '#5B21B6', border: '#DDD6FE' }, // 丁香紫
  { bg: '#FDF2F8', text: '#9D174D', border: '#FBCFE8' }, // 樱花粉
  { bg: '#FFF7ED', text: '#9A3412', border: '#FED7AA' }, // 暖落日
  { bg: '#ECFEFF', text: '#155E75', border: '#A5F3FC' }, // 冰川青
  { bg: '#F0FDFA', text: '#115E59', border: '#99F6E4' }, // 薄荷绿
  { bg: '#F8FAFC', text: '#334155', border: '#CBD5E1' }, // 冷烟灰
  { bg: '#FDF4FF', text: '#86198F', border: '#F5D0FE' }, // 浅芋紫
  { bg: '#EFF6FF', text: '#1D4ED8', border: '#93C5FD' }, // 湖天蓝
  { bg: '#FAF5FF', text: '#6B21A8', border: '#E9D5FF' }  // 罗兰紫
]

export function getCourseColorIndex(courseName: string): number {
  if (!courseName) return 0
  let hash = 0
  for (let i = 0; i < courseName.length; i++) {
    hash = (hash * 131 + courseName.charCodeAt(i)) >>> 0
  }
  return hash % MORANDI_PALETTE.length
}

export function splitClassroom(classroomStr?: string | null): { roomBuilding: string; roomNumber: string } {
  if (!classroomStr) return { roomBuilding: '', roomNumber: '' }
  const raw = String(classroomStr).trim().replace(/^@+/, '').trim()
  if (!raw) return { roomBuilding: '', roomNumber: '' }

  if (/[\r\n]+/.test(raw)) {
    const parts = raw.split(/[\r\n]+/)
    return { roomBuilding: parts[0].trim(), roomNumber: parts.slice(1).join(' ').trim() }
  }

  if (/[\s]+/.test(raw)) {
    const parts = raw.split(/[\s]+/)
    return { roomBuilding: parts[0].trim(), roomNumber: parts.slice(1).join(' ').trim() }
  }

  const match = raw.match(/^([^\d\s]+?)[-_]?(\d.*|[A-Za-z]\d.*|[A-Za-z]-.*)$/)
  if (match) {
    return { roomBuilding: match[1].trim(), roomNumber: match[2].trim() }
  }

  return { roomBuilding: raw, roomNumber: '' }
}

export interface PeriodDefinition {
  num: number
  start: string
  end: string
}

export const DEFAULT_PERIODS: PeriodDefinition[] = [
  { num: 1, start: '08:10', end: '08:55' },
  { num: 2, start: '09:00', end: '09:45' },
  { num: 3, start: '10:05', end: '10:50' },
  { num: 4, start: '10:55', end: '11:40' },
  { num: 5, start: '13:30', end: '14:15' },
  { num: 6, start: '14:20', end: '15:05' },
  { num: 7, start: '15:25', end: '16:10' },
  { num: 8, start: '16:15', end: '17:00' },
  { num: 9, start: '17:05', end: '17:50' },
  { num: 10, start: '18:50', end: '19:35' },
  { num: 11, start: '19:45', end: '20:30' }
]

export interface DateHeaderItem {
  dayName: string
  weekday: number
  month: number
  date: number
  dateStr: string
  isToday: boolean
}

export function getWeekDateHeaders(
  firstMondayStr = '2026-09-14',
  targetWeek = 1,
  includeWeekend = false
): DateHeaderItem[] {
  const parts = firstMondayStr ? firstMondayStr.split('-').map(Number) : [2026, 9, 14]
  const firstMondayDate = new Date(parts[0], parts[1] - 1, parts[2])
  const currentWeekMondayTime = firstMondayDate.getTime() + (targetWeek - 1) * 7 * 24 * 3600 * 1000

  const weekdays = includeWeekend
    ? ['一', '二', '三', '四', '五', '六', '日']
    : ['一', '二', '三', '四', '五']

  const today = new Date()
  const isSameDay = (d1: Date, d2: Date) =>
    d1.getFullYear() === d2.getFullYear() &&
    d1.getMonth() === d2.getMonth() &&
    d1.getDate() === d2.getDate()

  return weekdays.map((name, idx) => {
    const dayDate = new Date(currentWeekMondayTime + idx * 24 * 3600 * 1000)
    const m = String(dayDate.getMonth() + 1).padStart(2, '0')
    const d = String(dayDate.getDate()).padStart(2, '0')
    return {
      dayName: name,
      weekday: idx + 1,
      month: dayDate.getMonth() + 1,
      date: dayDate.getDate(),
      dateStr: `${m}-${d}`,
      isToday: isSameDay(dayDate, today)
    }
  })
}

export interface DayCourseInput {
  id: string
  courseName: string
  courseCode?: string
  teacherName?: string | null
  classroom?: string | null
  startPeriod: number
  endPeriod: number
  weeks: number[]
  teachingClassName?: string
  administrativeClasses?: string[]
  enrolledStudentCount?: number
  isPhysicalEducation?: boolean
  isInspectable?: boolean
  note?: string
}

export interface LayoutBlock extends DayCourseInput {
  roomBuilding: string
  roomNumber: string
  columnIndex: number
  totalSubColumns: number
  isConflict: boolean
  styleLeft: string
  styleWidth: string
  styleTop: string
  styleHeight: string
  color: MorandiColor
}

export function computeDayLayoutBlocks(
  dayCourses: DayCourseInput[] = [],
  totalPeriods = 11
): LayoutBlock[] {
  if (!dayCourses || dayCourses.length === 0) return []

  // 1. 按起始节次升序排序，节次相同时跨度大的在前
  const sorted = [...dayCourses].sort((a, b) => {
    if (a.startPeriod !== b.startPeriod) return a.startPeriod - b.startPeriod
    return (b.endPeriod - b.startPeriod) - (a.endPeriod - a.startPeriod)
  })

  // 2. 时间相交聚类 (Clustering)
  const clusters: DayCourseInput[][] = []
  for (const item of sorted) {
    const targetCluster = clusters.find(cluster =>
      cluster.some(existing =>
        item.startPeriod <= existing.endPeriod && item.endPeriod >= existing.startPeriod
      )
    )
    if (targetCluster) {
      targetCluster.push(item)
    } else {
      clusters.push([item])
    }
  }

  const result: LayoutBlock[] = []
  const totalPeriodsCount = Math.max(1, totalPeriods || 11)

  // 3. 针对每个聚类进行贪心子列分配
  for (const cluster of clusters) {
    const columnEnds: number[] = []
    const itemColumnMap = new Map<DayCourseInput, number>()

    for (const item of cluster) {
      let assignedIndex = -1
      for (let col = 0; col < columnEnds.length; col++) {
        if (columnEnds[col] < item.startPeriod) {
          assignedIndex = col
          columnEnds[col] = item.endPeriod
          break
        }
      }
      if (assignedIndex === -1) {
        columnEnds.push(item.endPeriod)
        assignedIndex = columnEnds.length - 1
      }
      itemColumnMap.set(item, assignedIndex)
    }

    const totalSubColumns = columnEnds.length

    // 4. 计算样式位置
    for (const item of cluster) {
      const colIdx = itemColumnMap.get(item) || 0
      const leftPercent = (colIdx / totalSubColumns) * 100
      const widthPercent = (1 / totalSubColumns) * 100
      const color = MORANDI_PALETTE[getCourseColorIndex(item.courseName)] || MORANDI_PALETTE[0]
      const { roomBuilding, roomNumber } = splitClassroom(item.classroom)

      const topPercent = ((item.startPeriod - 1) / totalPeriodsCount) * 100
      const span = Math.max(1, item.endPeriod - item.startPeriod + 1)
      const heightPercent = (span / totalPeriodsCount) * 100

      const styleTop = `calc(${topPercent.toFixed(4)}% + 2px)`
      const styleHeight = `calc(${heightPercent.toFixed(4)}% - 4px)`
      const styleLeft = totalSubColumns === 1 ? '2px' : `calc(${leftPercent.toFixed(4)}% + 2px)`
      const styleWidth = totalSubColumns === 1 ? 'calc(100% - 4px)' : `calc(${widthPercent.toFixed(4)}% - 4px)`

      result.push({
        ...item,
        roomBuilding,
        roomNumber,
        columnIndex: colIdx,
        totalSubColumns,
        isConflict: totalSubColumns > 1,
        styleLeft,
        styleWidth,
        styleTop,
        styleHeight,
        color
      })
    }
  }

  return result
}

export function formatWeeksText(weeks: number[] = []): string {
  if (!weeks || weeks.length === 0) return '无上课周次'
  const sorted = Array.from(new Set(weeks)).sort((a, b) => a - b)
  const min = sorted[0]
  const max = sorted[sorted.length - 1]

  const isContinuous = sorted.length === (max - min + 1)
  if (isContinuous) {
    return min === max ? `第${min}周` : `${min}-${max}周`
  }

  const isAllOdd = sorted.every(w => w % 2 === 1)
  if (isAllOdd && sorted.length === Math.floor((max - min) / 2) + 1) {
    return `单周(${min}-${max}周)`
  }

  const isAllEven = sorted.every(w => w % 2 === 0)
  if (isAllEven && sorted.length === Math.floor((max - min) / 2) + 1) {
    return `双周(${min}-${max}周)`
  }

  if (sorted.length <= 4) {
    return sorted.map(w => `${w}周`).join(',')
  }
  return `${min}-${max}周(部分)`
}
/** 独立时段不放进学校第1节网格；其实际时刻由独立课程条目展示。 */
export function partitionTimedCourses<T extends { time_basis?: string }>(rows: T[]) {
  return {
    periods: rows.filter(row => row.time_basis !== 'CLOCK'),
    clock: rows.filter(row => row.time_basis === 'CLOCK'),
  }
}
