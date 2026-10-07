/**
 * 高校标准节次与时段换算规范 (微信小程序端)
 * 全天划分为 1-11 小节，每两小节为一次正常课程时间（大节 1-6）：
 */
const STANDARD_PERIOD_SLOTS = {
  1: { sectionStart: 1, sectionEnd: 2, label: '第 1-2 节', time: '08:00-09:35' },
  2: { sectionStart: 3, sectionEnd: 4, label: '第 3-4 节', time: '10:05-11:40' },
  3: { sectionStart: 5, sectionEnd: 6, label: '第 5-6 节', time: '13:30-15:05' },
  4: { sectionStart: 7, sectionEnd: 8, label: '第 7-8 节', time: '15:25-17:00' },
  5: { sectionStart: 9, sectionEnd: 10, label: '第 9-10 节', time: '18:30-20:05' },
  6: { sectionStart: 11, sectionEnd: 11, label: '第 11 节', time: '20:15-21:50' },
};

function formatPeriodText(start, end, withTime = false) {
  if (start == null && end == null) return '';
  const s = Number(start != null ? start : end);
  const e = Number(end != null ? end : start);

  if (s >= 1 && s <= 6 && e >= 1 && e <= 6) {
    const sInfo = STANDARD_PERIOD_SLOTS[s];
    const eInfo = STANDARD_PERIOD_SLOTS[e];
    if (s === e && sInfo) {
      return withTime ? `${sInfo.label} (${sInfo.time})` : sInfo.label;
    }
    const secStart = sInfo ? sInfo.sectionStart : s;
    const secEnd = eInfo ? eInfo.sectionEnd : e;
    const secLabel = secStart === secEnd ? `第 ${secStart} 节` : `第 ${secStart}-${secEnd} 节`;
    if (withTime && sInfo && eInfo) {
      const startTime = sInfo.time.split('-')[0];
      const endTime = eInfo.time.split('-')[1];
      return `${secLabel} (${startTime}-${endTime})`;
    }
    return secLabel;
  }

  if (s === e) return `第 ${s} 节`;
  return `第 ${s}-${e} 节`;
}

module.exports = {
  formatPeriodText,
  STANDARD_PERIOD_SLOTS,
};
