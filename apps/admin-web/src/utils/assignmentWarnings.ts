const labels: Record<string, string> = {
  SELF_CLASS_WARNING: '被查名单包含本人行政班，按组规则允许',
  OWN_COURSE_WARNING: '与本人正式课程时间重叠，按组规则允许'
}
export const assignmentWarnings = (codes: readonly string[] = []) =>
  codes.map(code => labels[code] || code).join('；')
