// 引用的标准提示（契约 §3.8）。引用关系在后端 server/references.py 登记，这里只登记每种对象的中文名和打开它的地址；
// 删除确认、"被谁使用"、失效引用的写法都从这里生成，页面不各写各的。
import { h, type VNode } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { RouteLocationRaw, Router } from 'vue-router'
import { referencesApi, type BrokenRef, type ImpactNode, type RefKind, type Usage } from '../api'
import { confirmAction } from './feedback'

export const REF_KINDS: Record<RefKind, { label: string; open: (id: number) => RouteLocationRaw }> = {
  api: { label: '接口', open: (id) => ({ path: '/apis', query: { id: String(id) } }) },
  flow: { label: '业务流程', open: (id) => ({ path: '/flows', query: { edit: String(id) } }) },
  test: { label: '测试', open: (id) => ({ path: '/tests', query: { edit: String(id) } }) },
  dataset: { label: '数据集', open: (id) => ({ path: '/data', query: { tab: 'datasets', edit: String(id) } }) },
  file: { label: '文件', open: () => ({ path: '/data', query: { tab: 'files' } }) },
}

/** 失效引用在页面上的写法 */
export function brokenLabel(kind: RefKind, id: number): string {
  return `${REF_KINDS[kind].label}已删除（#${id}）`
}

/** 一组失效引用的说明：位置 → 写法 */
export function brokenSummary(refs: BrokenRef[]): string {
  return refs.map((r) => `${r.where.join('、')}：${brokenLabel(r.kind, r.id)}`).join('；')
}

/** 某一种被引用对象里已被删除的 id */
export function brokenIds(refs: BrokenRef[] | undefined, kind: RefKind): Set<number> {
  return new Set((refs ?? []).filter((r) => r.kind === kind).map((r) => r.id))
}

/** "被 1 个业务流程、2 个测试使用" */
export function usageSummary(usages: Usage[]): string {
  const counts = new Map<RefKind, number>()
  for (const u of usages) counts.set(u.kind, (counts.get(u.kind) ?? 0) + 1)
  return `被 ${[...counts].map(([kind, n]) => `${n} 个${REF_KINDS[kind].label}`).join('、')}使用`
}

function impactList(router: Router, nodes: ImpactNode[]): VNode {
  return h(
    'ul',
    nodes.map((n) =>
      h('li', [
        h('span', { class: 'muted' }, `${REF_KINDS[n.kind].label} `),
        h(
          'a',
          {
            class: 'dep-link',
            onClick: () => {
              // 关掉确认框（等于取消，什么都不删），再去处理
              ElMessageBox.close()
              void router.push(REF_KINDS[n.kind].open(n.id))
            },
          },
          n.name,
        ),
        n.where?.length ? h('span', { class: 'muted' }, ` · ${n.where.join('、')}`) : '',
        n.usedBy.length ? impactList(router, n.usedBy) : '',
      ]),
    ),
  )
}

/**
 * 删除任何定义之前调用：没有被引用时普通确认；被引用时列出会失效的引用（逐层，可点击打开），确认后只删这一个对象。
 * 返回 true 表示确认删除。
 */
export async function confirmDelete(router: Router, kind: RefKind, id: number, name: string): Promise<boolean> {
  const label = REF_KINDS[kind].label
  const impact = await referencesApi.impact(kind, id)
  if (!impact.usedBy.length) return confirmAction(`确定删除${label}「${name}」吗？`, `删除${label}`, true)
  try {
    await ElMessageBox.confirm(
      h('div', { class: 'dep-dialog' }, [
        h('p', `删除${label}「${name}」后，下面这些引用会失效：`),
        impactList(router, impact.usedBy),
        h('p', { class: 'dep-order' }, `失效的引用会保留，显示为"${label}已删除"；修好之前，引用它的对象不能试跑和运行。运行记录不受影响。`),
      ]),
      `删除${label}`,
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
