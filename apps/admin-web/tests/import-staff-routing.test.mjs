import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
import * as pinia from 'pinia'
import { parse, compileScript } from '@vue/compiler-sfc'

function load(source, imports) {
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022
  } }).outputText
  const module = { exports: {} }
  new Function('module', 'exports', 'require', code)(module, module.exports, name => {
    if (!(name in imports)) throw new Error(`Unexpected import: ${name}`)
    return imports[name]
  })
  return module.exports
}
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const campus = load(read('../src/api/campus.ts'), { './http': {} })

function sessionWith(capabilities) {
  pinia.setActivePinia(pinia.createPinia())
  const { useSessionStore } = load(read('../src/stores/session.ts'), {
    vue, pinia, '../api/auth': {}, '../api/academic': {}, '../api/http': {},
    '../api/campus': campus, '../api/workspaceHttp': {}
  })
  const session = useSessionStore()
  session.currentUser = { id: '1', permissions: [] }
  session.campusRuntime = { academic_scoped: true, business_scoped: true, scheduling: true }
  session.workspaces = [{ id: '1', name: 'Test college', capabilities }]
  session.workspaceCollegeId = '1'
  return session
}

function wizard(session) {
  const previews = []
  const runtimeVue = { ...vue, onUnmounted: () => {} }
  const imports = {
    vue: runtimeVue, '../stores/session': { useSessionStore: () => session },
    '../utils/importLimits': { IMPORT_MAX_BATCH: 100, IMPORT_TABLE_BYTES: 10485760, IMPORT_ARCHIVE_BYTES: 52428800 },
    '../api/importer': { uploadImportFile: async (target, file) => {
      previews.push({ target, filename: file.name }); return { id: 'draft1', target }
    } }
  }
  const composable = load(read('../src/composables/useImportWizard.ts'), imports)
  const source = compileScript(parse(read('../src/components/academic/ImportWizard.vue')).descriptor,
    { id: 'staff-routing' }).content
  const component = load(source, {
    vue: runtimeVue, 'vue-router': { useRouter: () => ({}) }, 'element-plus': {},
    '../../stores/session': imports['../stores/session'],
    '../../composables/useImportWizard': composable,
    '../../api/campus': { listCourseTypes: async () => [] }, '../../api/scopedAcademic': {},
    '../../api/importer': {}, '../../composables/useWorkspaceChanges': {},
    './ImportIdentityReview.vue': {}, './ImportReview.vue': {}, './ImportConflictHelp.vue': {},
    './importLabels': {}
  }).default
  const scope = vue.effectScope()
  const state = scope.run(() => component.setup({ initialTarget: 'faculty_staff', embedded: true,
    sources: [{ file: { name: 'staff.xlsx', size: 10 } }], resumeBatch: null },
  { expose: () => {}, emit: () => {} }))
  return { state, previews, scope }
}

test('staff permission follows the selected college and disappears on revocation', () => {
  const session = sessionWith(['staff.manage', 'course_schedule.import'])
  assert.equal(session.hasPermission('staff.manage'), true)
  session.workspaces[0].capabilities = ['course_schedule.import']
  assert.equal(session.hasPermission('staff.manage'), false)
})

test('recognized staff file reaches staff preview instead of timetable parsing', async () => {
  const { state, previews, scope } = wizard(sessionWith(['staff.manage', 'course_schedule.import']))
  try {
    await vue.nextTick()
    assert.equal(state.target.value, 'faculty_staff')
    await state.upload()
    assert.deepEqual(previews, [{ target: 'faculty_staff', filename: 'staff.xlsx' }])
  } finally { scope.stop() }
})

test('unavailable embedded type blocks upload instead of falling back to timetable', async () => {
  const { state, previews, scope } = wizard(sessionWith(['course_schedule.import']))
  try {
    await vue.nextTick()
    assert.equal(state.target.value, '')
    await state.upload()
    assert.equal(previews.length, 0)
  } finally { scope.stop() }
})
