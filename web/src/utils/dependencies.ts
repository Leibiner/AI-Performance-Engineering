// 删除被引用的定义之前，把整条依赖链（接口 ← 业务流程 ← 测试）摆出来，每一项都能点过去处理。
// 后端的 409 仍然兜底；这里是为了不让人一层一层地试。
import { h, type VNode } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { Router } from 'vue-router'
import type { ApiUsage, FlowUsage } from '../api'

export function stepPositions(u: ApiUsage): string {
  return [...u.initSteps.map((i) => `初始化第 ${i} 步`), ...u.steps.map((i) => `第 ${i} 步`)].join('、')
}

function link(text: string, go: () => void): VNode {
  return h(
    'a',
    {
      class: 'dep-link',
      onClick: () => {
        ElMessageBox.close()
        go()
      },
    },
    text,
  )
}

const openFlow = (router: Router, id: number) => () => void router.push({ path: '/flows', query: { edit: String(id) } })
const openTest = (router: Router, id: number) => () => void router.push({ path: '/tests', query: { edit: String(id) } })

function testsLine(router: Router, tests: FlowUsage[]): VNode {
  return h('div', { class: 'dep-sub' }, [
    '被测试使用：',
    ...tests.flatMap((t, i) => [
      ...(i ? ['、'] : []),
      link(t.testName, openTest(router, t.testId)),
      t.onlyThisFlow ? h('span', { class: 'muted' }, '（只有这个流程）') : '',
    ]),
  ])
}

function show(title: string, lead: string, items: VNode[], order: string): void {
  void ElMessageBox.alert(
    h('div', { class: 'dep-dialog' }, [h('p', lead), h('ul', items), h('p', { class: 'dep-order' }, order)]),
    title,
    { type: 'warning', confirmButtonText: '知道了', customClass: 'dep-box' },
  ).catch(() => undefined)
}

/** 接口被流程引用时；testsOf 是流程 id → 引用它的测试 */
export function showApiInUse(router: Router, apiName: string, usages: ApiUsage[], testsOf: Map<number, FlowUsage[]>): void {
  const items = usages.map((u) => {
    const tests = testsOf.get(u.flowId) ?? []
    return h('li', [
      link(u.flowName, openFlow(router, u.flowId)),
      h('span', { class: 'muted' }, ` · ${stepPositions(u)}${u.onlyThisApi ? ' · 流程里只有这个接口' : ''}`),
      tests.length ? testsLine(router, tests) : '',
    ])
  })
  const anyTests = usages.some((u) => (testsOf.get(u.flowId) ?? []).length > 0)
  const steps: string[] = []
  if (anyTests) steps.push('先处理引用这些流程的测试（只有这个流程的测试只能删除，有多个流程的可以在测试里移除它）')
  if (usages.some((u) => u.onlyThisApi)) steps.push('删除只有这个接口的流程')
  if (usages.some((u) => !u.onlyThisApi)) steps.push('在其余流程里移除这一步')
  steps.push('最后删除接口')
  show('不能删除接口', `接口「${apiName}」正被 ${usages.length} 个业务流程使用：`, items, `处理顺序：${steps.join(' → ')}`)
}

/** 流程被测试引用时 */
export function showFlowInUse(router: Router, flowName: string, usages: FlowUsage[]): void {
  const items = usages.map((t) =>
    h('li', [link(t.testName, openTest(router, t.testId)), t.onlyThisFlow ? h('span', { class: 'muted' }, ' · 测试里只有这个流程') : '']),
  )
  const steps: string[] = []
  if (usages.some((t) => t.onlyThisFlow)) steps.push('删除只有这个流程的测试')
  if (usages.some((t) => !t.onlyThisFlow)) steps.push('在其余测试里移除这个流程')
  steps.push('最后删除流程')
  show('不能删除业务流程', `业务流程「${flowName}」正被 ${usages.length} 个测试使用：`, items, `处理顺序：${steps.join(' → ')}`)
}
