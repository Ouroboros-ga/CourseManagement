import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const source = await readFile(new URL('../src/utils/studentTimetableLayout.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }
}).outputText

const {
  MORANDI_PALETTE,
  getCourseColorIndex,
  splitClassroom,
  getWeekDateHeaders,
  computeDayLayoutBlocks,
  formatWeeksText
} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('MORANDI_PALETTE and getCourseColorIndex', () => {
  assert.equal(MORANDI_PALETTE.length, 12)
  const idx1 = getCourseColorIndex('高等数学')
  const idx2 = getCourseColorIndex('高等数学')
  assert.equal(idx1, idx2)
  assert.ok(idx1 >= 0 && idx1 < 12)
})

test('splitClassroom parses building and room number', () => {
  assert.deepEqual(splitClassroom('教学楼4-109'), { roomBuilding: '教学楼', roomNumber: '4-109' })
  assert.deepEqual(splitClassroom('实验楼B-302'), { roomBuilding: '实验楼', roomNumber: 'B-302' })
  assert.deepEqual(splitClassroom('@机房 302'), { roomBuilding: '机房', roomNumber: '302' })
  assert.deepEqual(splitClassroom(''), { roomBuilding: '', roomNumber: '' })
})

test('getWeekDateHeaders generates correct weekday range', () => {
  const weekdays5 = getWeekDateHeaders('2026-09-14', 1, false)
  assert.equal(weekdays5.length, 5)
  assert.equal(weekdays5[0].dayName, '一')
  assert.equal(weekdays5[0].dateStr, '09-14')
  assert.equal(weekdays5[4].dayName, '五')
  assert.equal(weekdays5[4].dateStr, '09-18')

  const weekdays7 = getWeekDateHeaders('2026-09-14', 1, true)
  assert.equal(weekdays7.length, 7)
  assert.equal(weekdays7[6].dayName, '日')
  assert.equal(weekdays7[6].dateStr, '09-20')
})

test('computeDayLayoutBlocks handles non-overlapping and overlapping courses', () => {
  // Non-overlapping
  const coursesNonOverlap = [
    { id: '1', courseName: '高数', startPeriod: 1, endPeriod: 2, weeks: [1] },
    { id: '2', courseName: '英语', startPeriod: 3, endPeriod: 4, weeks: [1] }
  ]
  const blocks1 = computeDayLayoutBlocks(coursesNonOverlap, 11)
  assert.equal(blocks1.length, 2)
  assert.equal(blocks1[0].totalSubColumns, 1)
  assert.equal(blocks1[0].isConflict, false)
  assert.equal(blocks1[1].totalSubColumns, 1)
  assert.equal(blocks1[1].isConflict, false)

  // Overlapping courses on same periods
  const coursesOverlap = [
    { id: '1', courseName: '高数', startPeriod: 1, endPeriod: 2, weeks: [1] },
    { id: '2', courseName: '离散', startPeriod: 2, endPeriod: 3, weeks: [1] }
  ]
  const blocks2 = computeDayLayoutBlocks(coursesOverlap, 11)
  assert.equal(blocks2.length, 2)
  assert.equal(blocks2[0].totalSubColumns, 2)
  assert.equal(blocks2[0].isConflict, true)
  assert.equal(blocks2[1].totalSubColumns, 2)
  assert.equal(blocks2[1].isConflict, true)
  assert.notEqual(blocks2[0].columnIndex, blocks2[1].columnIndex)
})

test('formatWeeksText formats continuous, odd, even and discrete weeks', () => {
  assert.equal(formatWeeksText([1, 2, 3, 4, 5]), '1-5周')
  assert.equal(formatWeeksText([1, 3, 5, 7]), '单周(1-7周)')
  assert.equal(formatWeeksText([2, 4, 6, 8]), '双周(2-8周)')
  assert.equal(formatWeeksText([3]), '第3周')
  assert.equal(formatWeeksText([]), '无上课周次')
})
