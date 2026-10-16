import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'
import { ref, computed, watch, reactive } from 'vue'

const source = await readFile(new URL('../src/composables/usePageTabs.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }
}).outputText

test('usePageTabs maintains synchronous reactive state and syncs with route', async () => {
  const query = reactive({ tab: 'timetable' })
  const route = reactive({ path: '/dashboard/academic', query })
  let replacedTarget = null

  const router = {
    replace: async (target) => {
      replacedTarget = target
      // Simulate vue router async replace delay
      await new Promise(resolve => setTimeout(resolve, 15))
      Object.assign(query, target.query)
    }
  }

  // Strip imports and exports so we can execute in test scope
  const cleanBody = compiled
    .replace(/import\s*\{[^}]*\}\s*from\s*['"][^'"]*['"];?/g, '')
    .replace(/^export\s+/gm, '')

  const fn = new Function('ref', 'computed', 'watch', 'useRoute', 'useRouter', `
    ${cleanBody}
    return usePageTabs;
  `)

  const usePageTabs = fn(ref, computed, watch, () => route, () => router)

  const allowedTabs = ref(['timetable', 'classes', 'imports'])
  const tab = usePageTabs(() => allowedTabs.value)

  // 1. Initial value
  assert.equal(tab.value, 'timetable')

  // 2. Set tab synchronously: immediately updates tab.value
  tab.value = 'classes'
  assert.equal(tab.value, 'classes', 'tab.value must update synchronously on setter call')

  // Router replace was triggered asynchronously
  assert.deepEqual(replacedTarget, { query: { tab: 'classes' } })

  // 3. Wait for router replace to finish
  await new Promise(resolve => setTimeout(resolve, 25))
  assert.equal(tab.value, 'classes')
  assert.equal(route.query.tab, 'classes')

  // 4. External change (e.g. browser back button)
  route.query.tab = 'imports'
  await new Promise(resolve => setTimeout(resolve, 15))
  assert.equal(tab.value, 'imports', 'tab.value should update when route.query changes externally')

  // 5. Allowed list change removing current tab
  allowedTabs.value = ['timetable', 'classes']
  await new Promise(resolve => setTimeout(resolve, 15))
  assert.equal(tab.value, 'timetable', 'tab.value should fallback to first allowed tab')
})
