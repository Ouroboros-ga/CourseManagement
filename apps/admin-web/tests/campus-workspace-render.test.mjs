import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as vue from 'vue'
import ts from 'typescript'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../src/components/workspace/CampusWorkspace.vue', import.meta.url), 'utf8')

function loadComponent(overrides) {
  const script = compileScript(parse(source).descriptor, { id: 'CampusWorkspace', inlineTemplate: true })
  const code = ts.transpileModule(script.content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
  const module = { exports: {} }
  new Function('module', 'exports', 'require', code)(module, module.exports, name => {
    if (name === 'vue') return vue
    if (name.endsWith('/composables/useCampusConfiguration')) return overrides
    throw new Error(`Unexpected import ${name}`)
  })
  return module.exports.default
}

function workspaceState(overrides = {}) {
  const initial = {
    college: { id: 'A', capabilities: [] }, collegeId: 'A', groups: [], types: [],
    busy: false, error: '', isSuper: false, userId: 'U1', ...overrides
  }
  const state = { can: () => false, reload: async () => {}, loadWorkspaces: async () => {} }
  for (const [key, value] of Object.entries(initial)) state[key] = vue.ref(value)
  return state
}

function render(component, child) {
  const app = vue.createSSRApp({ render: () => vue.h(component, null, { default: () => [vue.h(child)] }) })
  app.directive('loading', { mounted() {}, unmounted() {} })
  for (const name of ['el-alert', 'el-empty', 'el-skeleton']) {
    app.component(name, vue.defineComponent({
      name,
      setup: (_props, { slots }) => () => vue.h('div', { class: name }, slots.default ? slots.default() : [])
    }))
  }
  return renderToString(app)
}
const textChild = label => vue.defineComponent({ name: 'Child', render: () => vue.h('p', label) })

test('a workspace with a college renders its content', async () => {
  const html = await render(loadComponent({ useCampusConfiguration: () => workspaceState() }), textChild('本院内容'))
  assert.match(html, /本院内容/)
})

test('an empty workspace explains itself instead of rendering nothing', async () => {
  const html = await render(
    loadComponent({ useCampusConfiguration: () => workspaceState({ college: null, collegeId: '' }) }),
    textChild('不该出现')
  )
  assert.match(html, /暂无可用学院/)
  assert.doesNotMatch(html, /不该出现/)
})

test('a loading workspace without a college renders the skeleton, not nothing', async () => {
  const html = await render(
    loadComponent({ useCampusConfiguration: () => workspaceState({ college: null, busy: true }) }),
    textChild('不该出现')
  )
  assert.match(html, /el-skeleton/)
  assert.doesNotMatch(html, /不该出现/)
})

test('a failed workspace read still reports the reason', async () => {
  const html = await render(
    loadComponent({ useCampusConfiguration: () => workspaceState({ college: null, error: '获取配置失败' }) }),
    textChild('不该出现')
  )
  assert.match(html, /获取配置失败/)
})

test('a throwing workspace child is reported instead of leaving a blank tab', () => {
  // SSR 单次渲染不会重跑，捕获后的重渲染在这里看不到；改为锁定模板契约：
  // 子组件抛错必须被捕获、必须显示、并且必须挡住原本会静默消失的插槽。
  assert.match(source, /onErrorCaptured/)
  assert.match(source, /college && !renderError/)
  const script = compileScript(parse(source).descriptor, { id: 'guard', inlineTemplate: true }).content
  assert.match(script, /本页内容渲染失败/)
})
