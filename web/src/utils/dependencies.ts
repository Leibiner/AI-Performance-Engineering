// 定义之间只是引用：每个对象可以单独删除，引用它的地方变成失效引用（契约 §3.1）。
// 删除被引用的对象之前，在确认框里列出会失效的地方（可点过去），确认后只删这一个对象。
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
        // 关掉确认框（等于取消，什么都不删），再去处理
        ElMessageBox.close()
        go()
      },
    },
    text,
  )
}

const openApi = (router: Router, id: number) => () => void router.push({ path: '/apis', query: { id: String(id) } })
const openFlow = (router: Router, id: number) => () => void router.push({ path: '/flows', query: { edit: String(id) } })
const openTest = (router: Router, id: number) => () => void router.push({ path: '/tests', query: { edit: String(id) } })

async function confirmImpact(title: string, lead: string, items: VNode[], consequence: string): Promise<boolean> {
  try {
    await ElMessageBox.confirm(
      h('div', { class: 'dep-dialog' }, [h('p', lead), h('ul', items), h('p', { class: 'dep-order' }, consequence)]),
      title,
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        customClass: 'dep-box',
      },
    )
    return true
  } catch {
    return false
  }
}

const KEEP_HISTORY = '运行记录不受影响。'

/** 接口被流程引用时；testsOf 是流程 id → 引用它的测试 */
export function confirmDeleteApi(router: Router, apiName: string, usages: ApiUsage[], testsOf: Map<number, FlowUsage[]>): Promise<boolean> {
  const items = usages.map((u) => {
    const tests = testsOf.get(u.flowId) ?? []
    return h('li', [
      link(u.flowName, openFlow(router, u.flowId)),
      h('span', { class: 'muted' }, ` · ${stepPositions(u)}`),
      tests.length
        ? h('div', { class: 'dep-sub' }, [
            '所在的测试：',
            ...tests.flatMap((t, i) => [...(i ? ['、'] : []), link(t.testName, openTest(router, t.testId))]),
          ])
        : '',
    ])
  })
  return confirmImpact(
    '删除接口',
    `接口「${apiName}」正被 ${usages.length} 个业务流程使用：`,
    items,
    `删除后这些步骤会失效（留在流程里，标为"接口已删除"），在换一个接口或移除这一步之前，这些流程和所在的测试不能试跑和运行。${KEEP_HISTORY}`,
  )
}

/** 流程被测试引用时 */
export function confirmDeleteFlow(router: Router, flowName: string, usages: FlowUsage[]): Promise<boolean> {
  return confirmImpact(
    '删除业务流程',
    `业务流程「${flowName}」正被 ${usages.length} 个测试使用：`,
    usages.map((t) => h('li', [link(t.testName, openTest(router, t.testId))])),
    `删除后这些测试里的这一项会失效（标为"流程已删除"），在换一个流程或移除它之前，这些测试不能运行。${KEEP_HISTORY}`,
  )
}

/** 数据集被流程绑定时 */
export function confirmDeleteDataset(router: Router, name: string, usedBy: { flowId: number; flowName: string }[]): Promise<boolean> {
  return confirmImpact(
    '删除数据集',
    `数据集「${name}」正被 ${usedBy.length} 个业务流程绑定：`,
    usedBy.map((u) => h('li', [link(u.flowName, openFlow(router, u.flowId))])),
    `删除后这些绑定会失效（标为"数据集已删除"），在换一个数据集或解除绑定之前，这些流程不能试跑和运行。${KEEP_HISTORY}`,
  )
}

/** 文件被接口的表单引用时 */
export function confirmDeleteFile(router: Router, name: string, usedBy: { apiId: number; apiName: string }[]): Promise<boolean> {
  return confirmImpact(
    '删除文件',
    `文件「${name}」正被 ${usedBy.length} 个接口的表单引用：`,
    usedBy.map((u) => h('li', [link(u.apiName, openApi(router, u.apiId))])),
    `删除后这些文件项会失效（标为"文件已删除"），在重新选择文件之前，这些接口不能以 form-data 发送。${KEEP_HISTORY}`,
  )
}
