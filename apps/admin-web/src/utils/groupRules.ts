import type { GroupConfiguration } from '../api/campus'

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return [...value].sort()
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => [key, canonical(item)]))
  }
  return value
}

export function sameGroupRules(a: GroupConfiguration | null | undefined, b: GroupConfiguration): boolean {
  if (!a) return false
  const normalize = (value: GroupConfiguration) => canonical({
    class_mode: 'ALL_AUTHORIZED', class_ids: [], teaching_class_overrides: {}, ...value
  })
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b))
}
